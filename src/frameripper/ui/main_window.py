from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QSettings, QSize, QStandardPaths, Qt, QThread, QThreadPool, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QProgressDialog,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from frameripper.analysis import autopick
from frameripper.analysis.data import Analysis
from frameripper.analysis.store import Store, video_key
from frameripper.analysis.worker import AnalysisThread
from frameripper.export.exporter import ExportItem, ExportOptions, ExportResult
from frameripper.export.naming import DEFAULT_TEMPLATE, display_timecode
from frameripper.marks import Marks
from frameripper.ui import theme
from frameripper.ui.dialogs import (
    AutoPickDialog,
    ExportDialog,
    PreferencesDialog,
    ShortcutsDialog,
    key_text,
)
from frameripper.ui.filmstrip import Filmstrip
from frameripper.ui.icons import icon
from frameripper.ui.panels import HoverPreview, MarksPanel
from frameripper.ui.timeline import Timeline
from frameripper.ui.viewer import Viewer, to_qimage
from frameripper.ui.workers import (
    DecodeThread,
    ExportTask,
    FullFrameTask,
    IndexThread,
    ThumbThread,
)
from frameripper.video.decoder import scaled_size
from frameripper.video.index import FrameIndex

log = logging.getLogger(__name__)

VIDEO_FILTER = (
    "Videos (*.mp4 *.mov *.m4v *.mkv *.webm *.avi *.wmv *.mts *.m2ts *.ts *.mpg *.mpeg "
    "*.flv *.3gp *.ogv *.mxf);;All files (*)"
)
THUMB_HEIGHT = 108
FILMSTRIP_STEPS = [
    ("Every frame", 1, False),
    ("Every 5 frames", 5, False),
    ("Every second", 1, True),
]
MAX_RECENT = 10


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings, store: Store):
        super().__init__()
        self.settings = settings
        self.store = store
        self.setWindowTitle("FrameRipper")
        self.setAcceptDrops(True)
        self.resize(1400, 900)

        self.index: FrameIndex | None = None
        self.decoder: DecodeThread | None = None
        self.thumbs: ThumbThread | None = None
        self.analysis: Analysis | None = None
        self.analysis_thread: AnalysisThread | None = None
        self.marks: Marks | None = None
        self.video_key: str | None = None
        self._index_thread: IndexThread | None = None
        self._opening: str | None = None
        self._pos = 0
        self._shown = -1
        self._hover_key: int | None = None
        self._play_origin: tuple[float, int] | None = None
        self._play_timer = QTimer(self, timeout=self._play_tick)
        self._play_timer.setTimerType(Qt.PreciseTimer)
        self._export_pool = QThreadPool(self)
        self._export_pool.setMaxThreadCount(1)
        self._tasks: set = set()
        self.actions: dict[str, QAction] = {}

        self._build_ui()
        self._build_actions()
        self._build_menus()
        self._build_transport()
        self._set_video_actions_enabled(False)

        geo = settings.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        state = settings.value("window/state")
        if state is not None:
            self.restoreState(state)

    # -- construction ----------------------------------------------------------

    def _build_ui(self) -> None:
        self.viewer = Viewer()
        self.viewer.fullResNeeded.connect(self._request_full)
        self.viewer.zoomChanged.connect(lambda t: self.zoom_label.setText(t))

        self.timeline = Timeline()
        self.timeline.seekRequested.connect(self.seek)
        self.timeline.stepRequested.connect(self.step)
        self.timeline.hovered.connect(self._timeline_hover)

        self.filmstrip = Filmstrip()
        self.filmstrip.seekRequested.connect(self.seek)
        self.filmstrip.stepRequested.connect(self.step)

        self.preview = HoverPreview(self)

        self.transport = QWidget(objectName="TransportBar")
        self.transport.setFixedHeight(52)

        bottom = QWidget(objectName="BottomPanel")
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(self.timeline)
        bl.addWidget(self.filmstrip)
        bl.addWidget(self.transport)

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.viewer, 1)
        cl.addWidget(bottom)
        self.setCentralWidget(central)

        self.marks_panel = MarksPanel()
        self.marks_panel.seekRequested.connect(self.seek)
        self.marks_panel.changed.connect(self._marks_changed)
        self.marks_panel.exportRequested.connect(self.export_marked)
        self.marks_panel.autoPickRequested.connect(self.auto_pick)
        self.marks_dock = QDockWidget("Marked frames", self)
        self.marks_dock.setObjectName("MarksDock")
        self.marks_dock.setWidget(self.marks_panel)
        self.marks_dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable)
        self.addDockWidget(Qt.RightDockWidgetArea, self.marks_dock)

        sb = self.statusBar()
        sb.setSizeGripEnabled(False)
        self.info_label = QLabel("No video")
        self.pos_label = QLabel()
        self.score_label = QLabel()
        self.analysis_label = QLabel()
        self.analysis_bar = QProgressBar()
        self.analysis_bar.setFixedWidth(110)
        self.analysis_bar.setRange(0, 1000)
        self.zoom_label = QLabel()
        sb.addWidget(self.info_label, 1)
        for w in (
            self.analysis_label,
            self.analysis_bar,
            self.score_label,
            self.pos_label,
            self.zoom_label,
        ):
            sb.addPermanentWidget(w)
        self.analysis_label.hide()
        self.analysis_bar.hide()

    def _act(
        self,
        key: str,
        text: str,
        shortcuts,
        slot,
        icon_name: str | None = None,
        checkable: bool = False,
        video: bool = True,
    ) -> QAction:
        a = QAction(text, self)
        if isinstance(shortcuts, str):
            shortcuts = [shortcuts]
        seqs = [QKeySequence(s) for s in shortcuts]
        a.setShortcuts(seqs)
        a.setShortcutContext(Qt.WindowShortcut)
        if icon_name:
            a.setIcon(icon(icon_name))
        a.setCheckable(checkable)
        tip = text.replace("...", "")
        if seqs:
            tip += f"  ({key_text(seqs[:1])})"
        a.setToolTip(tip)
        a.setProperty("needs_video", video)
        (a.toggled if checkable else a.triggered).connect(slot)
        self.addAction(a)
        self.actions[key] = a
        return a

    def _build_actions(self) -> None:
        A = self._act
        A("open", "Open video...", "Ctrl+O", self.open_dialog, "open", video=False)
        A("prefs", "Preferences...", "Ctrl+,", self.preferences, video=False)
        A("quit", "Quit", "Ctrl+Q", self.close, video=False)

        A("prev_frame", "Previous frame", "Left", lambda: self.step(-1), "prev_frame")
        A("next_frame", "Next frame", "Right", lambda: self.step(1), "next_frame")
        A(
            "prev_second",
            "Back 1 second",
            "Shift+Left",
            lambda: self.step_seconds(-1),
            "prev_second",
        )
        A(
            "next_second",
            "Forward 1 second",
            "Shift+Right",
            lambda: self.step_seconds(1),
            "next_second",
        )
        A("prev_10s", "Back 10 seconds", "Ctrl+Left", lambda: self.step_seconds(-10))
        A("next_10s", "Forward 10 seconds", "Ctrl+Right", lambda: self.step_seconds(10))
        A("first", "First frame", "Home", lambda: self.seek(0), "first")
        A("last", "Last frame", "End", lambda: self.seek(self.index.frame_count - 1), "last")
        A("play", "Play / pause", "Space", self.toggle_play, "play")
        A("prev_peak", "Previous sharp frame", "[", lambda: self.jump_peak(-1), "peak_prev")
        A("next_peak", "Next sharp frame", "]", lambda: self.jump_peak(1), "peak_next")
        A("goto", "Go to frame or time...", "Ctrl+G", self.goto_dialog)

        A("mark", "Mark / unmark frame", "M", self.toggle_mark, "mark")
        A("prev_mark", "Previous mark", ",", lambda: self.jump_mark(-1))
        A("next_mark", "Next mark", ".", lambda: self.jump_mark(1))
        A("remove_marks", "Remove mark", "Delete", self.remove_marks)
        A("auto_pick", "Auto-pick stills...", "Ctrl+Shift+A", self.auto_pick, "auto")
        A("accept_all", "Accept all suggestions", [], self._accept_all)
        A("clear_marks", "Clear all marks", [], self._clear_marks)

        A("quick_export", "Export frame", "S", self.quick_export, "export")
        A("export_as", "Export frame as...", "Ctrl+Shift+S", self.export_as)
        A("export_marked", "Export marked frames...", "Ctrl+E", self.export_marked)
        A("copy", "Copy frame to clipboard", "Ctrl+C", self.copy_frame, "clipboard")
        A("export_folder", "Change export folder...", [], self.choose_export_folder, video=False)
        A("open_folder", "Open export folder", [], self.open_export_folder, video=False)

        A("loupe", "Pixel loupe", "Z", self.viewer.set_loupe, "loupe", checkable=True)
        A("fit", "Fit to window", ["1", "F"], self.viewer.set_fit, "fit")
        A("actual", "Actual pixels (100%)", "2", lambda: self.viewer.set_actual(), "actual")
        A("zoom_in", "Zoom in", ["=", "+"], lambda: self.viewer.zoom_by(1.25))
        A("zoom_out", "Zoom out", "-", lambda: self.viewer.zoom_by(0.8))

        A("shortcuts", "Keyboard shortcuts", ["?", "F1"], self.show_shortcuts, video=False)

    def _build_menus(self) -> None:
        mb = self.menuBar()
        a = self.actions

        m = mb.addMenu("&File")
        m.addAction(a["open"])
        self.recent_menu = m.addMenu("Open recent")
        self.recent_menu.aboutToShow.connect(self._fill_recent)
        m.addSeparator()
        for k in ("quick_export", "export_as", "export_marked", "copy"):
            m.addAction(a[k])
        m.addSeparator()
        m.addAction(a["export_folder"])
        m.addAction(a["open_folder"])
        m.addSeparator()
        m.addAction(a["prefs"])
        m.addAction(a["quit"])

        m = mb.addMenu("&Navigate")
        for k in (
            "play",
            None,
            "prev_frame",
            "next_frame",
            "prev_second",
            "next_second",
            "prev_10s",
            "next_10s",
            "first",
            "last",
            None,
            "prev_peak",
            "next_peak",
            None,
            "goto",
        ):
            m.addSeparator() if k is None else m.addAction(a[k])

        m = mb.addMenu("&Marks")
        for k in (
            "mark",
            "prev_mark",
            "next_mark",
            None,
            "auto_pick",
            "accept_all",
            None,
            "clear_marks",
        ):
            m.addSeparator() if k is None else m.addAction(a[k])

        m = mb.addMenu("&View")
        for k in ("fit", "actual", "zoom_in", "zoom_out", "loupe"):
            m.addAction(a[k])
        m.addSeparator()
        step_menu = m.addMenu("Filmstrip spacing")
        self._step_group = QActionGroup(self)
        saved = int(self.settings.value("filmstrip/step", 0))
        for i, (label, _, _) in enumerate(FILMSTRIP_STEPS):
            act = step_menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(i == saved)
            act.setData(i)
            self._step_group.addAction(act)
        self._step_group.triggered.connect(lambda act: self._set_strip_step(act.data()))
        panel_toggle = self.marks_dock.toggleViewAction()
        panel_toggle.setText("Marked frames panel")
        panel_toggle.setShortcut(QKeySequence("Ctrl+M"))
        self.addAction(panel_toggle)
        m.addAction(panel_toggle)

        m = mb.addMenu("&Help")
        m.addAction(a["shortcuts"])
        about = m.addAction("About FrameRipper")
        about.triggered.connect(self._about)

    def _tool(self, action_key: str, size: int = 34) -> QToolButton:
        b = QToolButton()
        b.setDefaultAction(self.actions[action_key])
        b.setIconSize(QSize(20, 20))
        b.setFixedSize(size, size)
        b.setFocusPolicy(Qt.NoFocus)
        b.setAutoRaise(True)
        return b

    def _build_transport(self) -> None:
        row = QHBoxLayout(self.transport)
        row.setContentsMargins(10, 6, 10, 8)
        row.setSpacing(2)

        row.addWidget(self._tool("open"))
        row.addSpacing(10)
        self.time_label = QLabel("--:--:--.---")
        self.time_label.setMinimumWidth(190)
        self.time_label.setStyleSheet(
            "font-family: Consolas, 'Cascadia Mono', monospace; font-size: 10.5pt;"
            f"color: {theme.TEXT};"
        )
        row.addWidget(self.time_label)
        row.addStretch(1)

        for k in ("first", "prev_second", "prev_frame"):
            row.addWidget(self._tool(k))
        self.play_button = self._tool("play", 38)
        self.play_button.setObjectName("PlayButton")
        self.play_button.setIconSize(QSize(22, 22))
        row.addSpacing(4)
        row.addWidget(self.play_button)
        row.addSpacing(4)
        for k in ("next_frame", "next_second", "last"):
            row.addWidget(self._tool(k))

        row.addSpacing(18)
        row.addWidget(self._tool("prev_peak"))
        self.mark_button = self._tool("mark")
        row.addWidget(self.mark_button)
        row.addWidget(self._tool("next_peak"))
        row.addSpacing(18)
        row.addWidget(self._tool("quick_export"))
        row.addWidget(self._tool("copy"))
        row.addStretch(1)

        self.step_combo = QComboBox()
        self.step_combo.setFocusPolicy(Qt.NoFocus)
        self.step_combo.setToolTip("Filmstrip spacing")
        for label, _, _ in FILMSTRIP_STEPS:
            self.step_combo.addItem(label)
        self.step_combo.setCurrentIndex(int(self.settings.value("filmstrip/step", 0)))
        self.step_combo.currentIndexChanged.connect(self._set_strip_step)
        row.addWidget(self.step_combo)
        row.addSpacing(10)
        for k in ("loupe", "fit", "actual"):
            row.addWidget(self._tool(k))

    def _set_video_actions_enabled(self, on: bool) -> None:
        for a in self.actions.values():
            if a.property("needs_video"):
                a.setEnabled(on)

    # -- opening / closing -----------------------------------------------------

    def open_dialog(self) -> None:
        start = self.settings.value("last_dir", "")
        path, _ = QFileDialog.getOpenFileName(self, "Open video", start, VIDEO_FILTER)
        if path:
            self.open_video(path)

    def open_video(self, path: str) -> None:
        path = str(Path(path))
        self.settings.setValue("last_dir", str(Path(path).parent))
        self._close_video()
        self._opening = path
        self.viewer.clear(f"Opening {Path(path).name}...")
        self.info_label.setText(f"Opening {Path(path).name}...")
        t = IndexThread(path, self)
        t.loaded.connect(self._on_indexed)
        t.failed.connect(self._on_open_failed)
        t.finished.connect(t.deleteLater)
        self._index_thread = t
        t.start()

    def _on_open_failed(self, message: str) -> None:
        self._opening = None
        self.viewer.clear("Drop a video here\nor press Ctrl+O")
        self.info_label.setText("No video")
        QMessageBox.warning(self, "Could not open video", message)

    def _on_indexed(self, index: FrameIndex) -> None:
        if self._opening is None or Path(index.path) != Path(self._opening).resolve():
            return  # superseded by a later open
        self._opening = None
        self.index = index
        self._pos = 0
        self._shown = -1

        screen = self.screen()
        dpr = screen.devicePixelRatio()
        size = screen.size()
        max_size = (int(size.width() * dpr), int(size.height() * dpr))
        cache_mb = int(self.settings.value("cache_mb", 1024))
        self.decoder = DecodeThread(index, max_size, cache_mb * 1024 * 1024, self)
        self.viewer.capped_ratio = scaled_size(index, *max_size)[0] / index.display_size[0]
        self.decoder.frameReady.connect(self._on_frame)
        self.decoder.start(QThread.HighPriority)

        self.thumbs = ThumbThread(index, THUMB_HEIGHT, 96 * 1024 * 1024, self)
        self.thumbs.thumbReady.connect(self._on_thumb)
        self.thumbs.start()

        try:
            self.video_key = video_key(index.path)
        except OSError:
            self.video_key = None
        cached = (
            self.store.load_analysis(self.video_key, index.frame_count) if self.video_key else None
        )
        self.analysis = cached or Analysis.empty(index.frame_count)
        session = self.store.load_session(self.video_key) if self.video_key else {}
        self.marks = Marks.from_dict(session, index.frame_count)

        w, h = index.display_size
        self.timeline.set_video(index.frame_count)
        self.timeline.set_analysis(self.analysis)
        self.timeline.set_marks(self.marks)
        self.filmstrip.set_source(self.thumbs, index.frame_count, w / h)
        self._set_strip_step(self.step_combo.currentIndex())
        self.filmstrip.set_analysis(self.analysis)
        self.filmstrip.set_marks(self.marks)
        self.marks_panel.set_source(index, self.marks, self.analysis, self.thumbs)

        name = Path(index.path).name
        self.setWindowTitle(f"{name} - FrameRipper")
        self.info_label.setText(
            f"{name}   {w}×{h}   {index.avg_fps:.3g} fps   {index.codec}   "
            f"{display_timecode(index.duration)}"
        )
        self._add_recent(index.path)
        self._set_video_actions_enabled(True)

        if not self.analysis.complete:
            self._start_analysis()
        else:
            self._analysis_done(save=False)

        last = int(session.get("frame", 0))
        self.seek(index.clamp(last))
        if last > 0:
            self.viewer.toast(f"Resumed at frame {last}")

    def _start_analysis(self) -> None:
        t = AnalysisThread(self.index, self.analysis, self)
        t.progressed.connect(self._analysis_progress)
        t.completed.connect(self._analysis_done)
        t.failed.connect(lambda msg: self.statusBar().showMessage(f"Analysis stopped: {msg}", 6000))
        self.analysis_thread = t
        self.analysis_label.setText("Analysing sharpness")
        self.analysis_label.show()
        self.analysis_bar.setValue(0)
        self.analysis_bar.show()
        t.start(QThread.LowPriority)

    def _analysis_progress(self, done: int) -> None:
        if self.index is None:
            return
        self.analysis_bar.setValue(int(done * 1000 / max(1, self.index.frame_count)))
        self.timeline.update()
        self.filmstrip.update()
        self._update_status()

    def _analysis_done(self, save: bool = True) -> None:
        self.analysis_label.hide()
        self.analysis_bar.hide()
        if save and self.video_key and self.analysis is not None and self.analysis.complete:
            try:
                self.store.save_analysis(self.video_key, self.analysis)
            except OSError as e:
                log.warning("could not cache analysis: %s", e)
        self.timeline.update()
        self.filmstrip.update()
        self.marks_panel.refresh()
        self._update_status()

    def _save_session(self) -> None:
        if self.video_key and self.marks is not None:
            try:
                self.store.save_session(
                    self.video_key, {**self.marks.to_dict(), "frame": self._pos}
                )
            except OSError as e:
                log.warning("could not save session: %s", e)

    def _close_video(self) -> None:
        self._stop_playback()
        self.preview.hide()
        self._save_session()
        for t in (self.analysis_thread, self.decoder, self.thumbs):
            if t is not None:
                t.stop()
        for t in (self.analysis_thread, self.decoder, self.thumbs):
            if t is not None:
                t.wait(5000)
                t.deleteLater()
        self.analysis_thread = self.decoder = self.thumbs = None
        self.index = self.analysis = self.marks = None
        self.video_key = None
        self.timeline.set_video(0)
        self.timeline.set_analysis(None)
        self.timeline.set_marks(None)
        self.filmstrip.set_source(None, 0, 16 / 9)
        self.marks_panel.set_source(None, None, None, None)
        self.analysis_label.hide()
        self.analysis_bar.hide()
        self._set_video_actions_enabled(False)
        self.pos_label.clear()
        self.score_label.clear()
        self.time_label.setText("--:--:--.---")
        self.setWindowTitle("FrameRipper")

    def closeEvent(self, e) -> None:
        self._close_video()
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self._export_pool.waitForDone(10000)
        super().closeEvent(e)

    # -- drag and drop ---------------------------------------------------------

    def dragEnterEvent(self, e) -> None:
        if any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e) -> None:
        for u in e.mimeData().urls():
            if u.isLocalFile():
                self.open_video(u.toLocalFile())
                break

    # -- recent files ------------------------------------------------------------

    def _recent(self) -> list[str]:
        value = self.settings.value("recent", [])
        if isinstance(value, str):
            value = [value]
        return [v for v in (value or []) if v]

    def _add_recent(self, path: str) -> None:
        items = [p for p in self._recent() if Path(p) != Path(path)]
        self.settings.setValue("recent", [path, *items][:MAX_RECENT])

    def _fill_recent(self) -> None:
        self.recent_menu.clear()
        items = [p for p in self._recent() if Path(p).exists()]
        if not items:
            self.recent_menu.addAction("No recent videos").setEnabled(False)
            return
        for p in items:
            act = self.recent_menu.addAction(Path(p).name)
            act.setToolTip(p)
            act.triggered.connect(lambda _=False, p=p: self.open_video(p))
        self.recent_menu.addSeparator()
        self.recent_menu.addAction("Clear list").triggered.connect(
            lambda: self.settings.setValue("recent", [])
        )

    # -- navigation ------------------------------------------------------------

    def seek(self, n: int, from_playback: bool = False) -> None:
        if self.index is None or self.decoder is None:
            return
        if not from_playback:
            self._stop_playback()
        n = self.index.clamp(n)
        self._pos = n
        self.viewer.frame_changed()
        full = self.viewer.wants_full_res()
        arr = self.decoder.cached(n, full)
        if arr is not None:
            self._show(n, full, arr)
        else:
            stand_in = self.decoder.cached(n) if full else None
            if stand_in is not None:
                self._show(n, False, stand_in)
            self.decoder.request(n, full)
        self.timeline.set_position(n)
        self.filmstrip.set_position(n)
        self._update_status()
        self._update_badge()

    def step(self, delta: int) -> None:
        if self.index is not None:
            self.seek(self._pos + delta)

    def step_seconds(self, seconds: float) -> None:
        if self.index is None:
            return
        target = self.index.frame_at_time(self.index.time_of(self._pos) + seconds)
        if target == self._pos:
            target += 1 if seconds > 0 else -1
        self.seek(target)

    def jump_peak(self, direction: int) -> None:
        a = self.analysis
        if a is None or a.analysed == 0:
            self.viewer.toast("Sharpness analysis hasn't reached this part yet")
            return
        radius = max(2, round(self.index.avg_fps / 2))
        peaks = a.peaks(radius)
        if direction > 0:
            ahead = peaks[peaks > self._pos]
            target = int(ahead[0]) if len(ahead) else None
        else:
            behind = peaks[peaks < self._pos]
            target = int(behind[-1]) if len(behind) else None
        if target is None:
            self.viewer.toast("No sharper frames in that direction")
        else:
            self.seek(target)

    def jump_mark(self, direction: int) -> None:
        if self.marks is None:
            return
        target = (
            self.marks.next_after(self._pos) if direction > 0 else self.marks.prev_before(self._pos)
        )
        if target is None:
            self.viewer.toast("No more marks that way")
        else:
            self.seek(target)

    def goto_dialog(self) -> None:
        text, ok = QInputDialog.getText(
            self, "Go to", "Frame number, or time such as 1:23.5 or 83.5s:"
        )
        if not ok or not text.strip():
            return
        n = self._parse_position(text.strip())
        if n is None:
            self.viewer.toast(f"Couldn't understand '{text}'")
        else:
            self.seek(n)

    def _parse_position(self, text: str) -> int | None:
        if re.fullmatch(r"\d+", text):
            return int(text)
        m = re.fullmatch(r"(?:(\d+):)?(?:(\d+):)?(\d+(?:\.\d+)?)s?", text)
        if not m:
            return None
        parts = [p for p in m.groups() if p is not None]
        seconds = 0.0
        for p in parts:
            seconds = seconds * 60 + float(p)
        return self.index.frame_at_time(seconds)

    # -- playback --------------------------------------------------------------

    def toggle_play(self) -> None:
        if self.index is None:
            return
        if self._play_timer.isActive():
            self._stop_playback()
            return
        if self._pos >= self.index.frame_count - 1:
            self.seek(0)
        self._play_origin = (time.perf_counter(), self._pos)
        self._play_timer.start(max(4, int(500 / max(self.index.avg_fps, 1))))
        self.actions["play"].setIcon(icon("pause"))

    def _stop_playback(self) -> None:
        if self._play_timer.isActive():
            self._play_timer.stop()
            self.actions["play"].setIcon(icon("play"))

    def _play_tick(self) -> None:
        if self.index is None or self._play_origin is None:
            self._stop_playback()
            return
        t0, n0 = self._play_origin
        elapsed = time.perf_counter() - t0
        n = self.index.frame_at_time(self.index.time_of(n0) + elapsed)
        if n >= self.index.frame_count - 1:
            self.seek(self.index.frame_count - 1, from_playback=True)
            self._stop_playback()
        elif n != self._pos:
            self.seek(n, from_playback=True)

    # -- frames ----------------------------------------------------------------

    def _on_frame(self, n: int, full: bool, arr: np.ndarray) -> None:
        if self.index is None:
            return
        if n == self._pos:
            self._show(n, full, arr)
        elif self._shown != self._pos:
            # Still waiting on the current frame; show the nearest so scrubbing feels live.
            self._show(n, full, arr)

    def _show(self, n: int, full: bool, arr: np.ndarray) -> None:
        self._shown = n
        # Screen-capped frames of small videos are already native resolution.
        full = full or arr.shape[1] >= self.index.display_size[0]
        self.viewer.set_frame(arr, full, self.index.display_size)

    def _request_full(self) -> None:
        if self.decoder is None:
            return
        arr = self.decoder.cache.get((self._pos, True))
        if arr is not None:
            self._show(self._pos, True, arr)
        else:
            self.decoder.request(self._pos, full=True)

    def _on_thumb(self, n: int) -> None:
        if n == self._hover_key and self.preview.isVisible():
            self.preview.set_image(self.thumbs.thumb(n))

    def _timeline_hover(self, n: int, anchor) -> None:
        if n < 0 or self.index is None or self.thumbs is None:
            self.preview.hide()
            self._hover_key = None
            if self.thumbs is not None:
                self.thumbs.want("preview", [])
            return
        # Keyframes decode with a single seek, which keeps hover previews snappy.
        key = self.index.keyframe_before(n)
        self._hover_key = key
        self.thumbs.want("preview", [key])
        text = display_timecode(self.index.time_of(n))
        score = self.analysis.score(n) if self.analysis is not None else None
        if score is not None:
            text += f"   sharp {score:.0f}"
        size = QSize(self.thumbs.width, self.thumbs.height)
        self.preview.show_at(anchor, self.thumbs.thumb(key), text, size)

    def _set_strip_step(self, i: int) -> None:
        i = max(0, min(int(i), len(FILMSTRIP_STEPS) - 1))
        self.settings.setValue("filmstrip/step", i)
        if self.step_combo.currentIndex() != i:
            self.step_combo.setCurrentIndex(i)
        for act in self._step_group.actions():
            act.setChecked(act.data() == i)
        _, step, per_second = FILMSTRIP_STEPS[i]
        if per_second and self.index is not None:
            step = max(1, round(self.index.avg_fps))
        self.filmstrip.set_step(step)

    # -- status ----------------------------------------------------------------

    def _update_status(self) -> None:
        if self.index is None:
            return
        n, total = self._pos, self.index.frame_count
        t = display_timecode(self.index.time_of(n))
        self.time_label.setText(f"{t}  /  {display_timecode(self.index.duration)}")
        self.pos_label.setText(f"Frame {n:,} / {total - 1:,}")
        score = self.analysis.score(n) if self.analysis is not None else None
        if score is None:
            self.score_label.setText("Sharpness --")
        else:
            color = theme.heat_color(score / 100).name()
            self.score_label.setText(f"<span style='color:{color}'>●</span> Sharpness {score:.0f}")

    def _update_badge(self) -> None:
        m = self.marks
        if m is None:
            self.viewer.set_badge(None)
            self.actions["mark"].setIcon(icon("mark"))
            return
        if m.is_marked(self._pos):
            self.viewer.set_badge("Marked")
            self.actions["mark"].setIcon(icon("marked", accent=True))
        elif m.is_suggested(self._pos):
            self.viewer.set_badge("Suggested")
            self.actions["mark"].setIcon(icon("mark"))
        else:
            self.viewer.set_badge(None)
            self.actions["mark"].setIcon(icon("mark"))

    # -- marks -----------------------------------------------------------------

    def toggle_mark(self) -> None:
        if self.marks is None:
            return
        self.marks.toggle(self._pos)
        self._marks_changed()

    def _marks_changed(self) -> None:
        self.timeline.update()
        self.filmstrip.update()
        self.marks_panel.refresh()
        self._update_badge()
        self._save_session()

    def remove_marks(self) -> None:
        if self.marks is None:
            return
        if self.marks_panel.list.selectedItems():
            self.marks_panel.remove_selected()
        elif self.marks.is_marked(self._pos) or self.marks.is_suggested(self._pos):
            self.marks.remove(self._pos)
            self._marks_changed()

    def _accept_all(self) -> None:
        if self.marks is not None:
            self.marks.accept_all()
            self._marks_changed()

    def _clear_marks(self) -> None:
        if self.marks is None or not self.marks.all():
            return
        if (
            QMessageBox.question(self, "Clear marks", "Remove all marks and suggestions?")
            == QMessageBox.Yes
        ):
            self.marks.marked.clear()
            self.marks.clear_suggestions()
            self._marks_changed()

    def auto_pick(self) -> None:
        if self.index is None or self.analysis is None:
            return
        a = self.analysis
        if a.analysed == 0:
            self.viewer.toast("Wait for sharpness analysis to get started")
            return
        dlg = AutoPickDialog(
            a.analysed / a.frame_count,
            float(self.settings.value("autopick/window", 2.0)),
            str(self.settings.value("autopick/mode", "window")),
            self,
        )
        if dlg.exec() != AutoPickDialog.Accepted:
            return
        mode = dlg.mode()
        self.settings.setValue("autopick/mode", mode)
        self.settings.setValue("autopick/window", dlg.window.value())
        if mode == "scene":
            picks = autopick.pick_per_scene(a.sharpness, a.motion, a.change)
        else:
            times = (self.index.pts - self.index.pts[0]) * float(self.index.time_base)
            picks = autopick.pick_per_window(
                a.sharpness, a.motion, a.change, times, dlg.window.value()
            )
        self.marks.set_suggestions(picks, replace=dlg.replace.isChecked())
        self._marks_changed()
        if not self.marks_dock.isVisible():
            self.marks_dock.show()
        self.viewer.toast(f"Suggested {len(picks)} frames, review them in the panel")

    # -- export ----------------------------------------------------------------

    def _export_folder(self) -> Path:
        saved = self.settings.value("export/folder", "")
        if saved:
            return Path(saved)
        pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
        return Path(pictures) / "FrameRipper"

    def _export_options(self) -> ExportOptions:
        return ExportOptions(
            folder=self._export_folder(),
            fmt=str(self.settings.value("export/format", "png")),
            quality=int(self.settings.value("export/quality", 95)),
            template=str(self.settings.value("export/template", DEFAULT_TEMPLATE)),
        )

    def _save_export_options(self, opts: ExportOptions) -> None:
        self.settings.setValue("export/folder", str(opts.folder))
        self.settings.setValue("export/format", opts.fmt)
        self.settings.setValue("export/quality", opts.quality)
        self.settings.setValue("export/template", opts.template)

    def _item(self, n: int, i: int = 1) -> ExportItem:
        score = self.analysis.score(n) if self.analysis is not None else None
        return ExportItem(frame=n, score=score, n=i)

    def _sample(self) -> dict:
        n = self._pos
        score = self.analysis.score(n) if self.analysis is not None else None
        return dict(name=self.index.name, frame=n, seconds=self.index.time_of(n), score=score, n=1)

    def _run_export(self, items: list[ExportItem], opts: ExportOptions, batch: bool) -> None:
        task = ExportTask(self.index, items, opts)
        self._tasks.add(task.signals)
        progress = None
        if batch:
            progress = QProgressDialog("Exporting frames...", "Cancel", 0, len(items), self)
            progress.setWindowTitle("Export")
            progress.setMinimumDuration(400)
            progress.setValue(0)
            progress.canceled.connect(lambda: setattr(task, "cancel_requested", True))
            task.signals.progress.connect(lambda done, total: progress.setValue(done))

        def finished(result: ExportResult, signals=task.signals) -> None:
            self._tasks.discard(signals)
            if progress is not None:
                progress.reset()
                progress.deleteLater()
            self._export_finished(result, opts)

        task.signals.done.connect(finished)
        self._export_pool.start(task)

    def _export_finished(self, result: ExportResult, opts: ExportOptions) -> None:
        if result.errors:
            QMessageBox.warning(
                self,
                "Export problems",
                f"{len(result.errors)} frame(s) failed:\n\n" + "\n".join(result.errors[:10]),
            )
        if len(result.paths) == 1:
            p = result.paths[0]
            self.viewer.toast(f"Saved {p.name}  →  {p.parent}")
        elif result.paths:
            self.viewer.toast(f"Saved {len(result.paths)} frames to {opts.folder}")

    def quick_export(self) -> None:
        if self.index is None:
            return
        opts = self._export_options()
        self._run_export([self._item(self._pos)], opts, batch=False)

    def export_as(self) -> None:
        if self.index is None:
            return
        dlg = ExportDialog(self._export_options(), self._sample(), 1, self, "Export frame")
        if dlg.exec() == ExportDialog.Accepted:
            opts = dlg.options()
            self._save_export_options(opts)
            self._run_export([self._item(self._pos)], opts, batch=False)

    def export_marked(self) -> None:
        if self.index is None or self.marks is None:
            return
        frames = self.marks.marked
        if not frames:
            if self.marks.suggested:
                self.viewer.toast("Accept some suggestions first (or press M on frames you like)")
            else:
                self.viewer.toast("No marked frames yet; press M to mark the current frame")
            return
        dlg = ExportDialog(
            self._export_options(), self._sample(), len(frames), self, "Export marked frames"
        )
        if dlg.exec() == ExportDialog.Accepted:
            opts = dlg.options()
            self._save_export_options(opts)
            items = [self._item(n, i + 1) for i, n in enumerate(frames)]
            self._run_export(items, opts, batch=True)

    def copy_frame(self) -> None:
        if self.index is None:
            return
        task = FullFrameTask(self.index, self._pos)
        self._tasks.add(task.signals)
        n = self._pos

        def done(arr, signals=task.signals) -> None:
            self._tasks.discard(signals)
            if arr is None:
                self.viewer.toast("Couldn't decode that frame")
                return
            QApplication.clipboard().setImage(to_qimage(arr).copy())
            self.viewer.toast(f"Copied frame {n} to the clipboard")

        task.signals.frame.connect(done)
        self._export_pool.start(task)

    def choose_export_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Export folder", str(self._export_folder()))
        if folder:
            self.settings.setValue("export/folder", folder)
            self.viewer.toast(f"Exports will go to {folder}")

    def open_export_folder(self) -> None:
        folder = self._export_folder()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    # -- misc ------------------------------------------------------------------

    def preferences(self) -> None:
        dlg = PreferencesDialog(int(self.settings.value("cache_mb", 1024)), self)
        if dlg.exec() == PreferencesDialog.Accepted:
            self.settings.setValue("cache_mb", dlg.cache.value())

    def show_shortcuts(self) -> None:
        a = self.actions

        def rows(keys):
            return [(a[k].text().replace("...", ""), key_text(a[k].shortcuts())) for k in keys]

        groups = [
            (
                "Navigate",
                rows(
                    [
                        "prev_frame",
                        "next_frame",
                        "prev_second",
                        "next_second",
                        "prev_10s",
                        "next_10s",
                        "first",
                        "last",
                        "play",
                        "goto",
                    ]
                ),
            ),
            (
                "Find stills",
                rows(
                    [
                        "prev_peak",
                        "next_peak",
                        "mark",
                        "prev_mark",
                        "next_mark",
                        "remove_marks",
                        "auto_pick",
                    ]
                ),
            ),
            ("Export", rows(["quick_export", "export_as", "export_marked", "copy"])),
            (
                "View",
                rows(["fit", "actual", "zoom_in", "zoom_out", "loupe"])
                + [
                    ("Marked frames panel", "Ctrl+M"),
                    ("Zoom at cursor", "Mouse wheel"),
                    ("Toggle fit / 100%", "Double-click"),
                ],
            ),
            ("App", rows(["open", "prefs", "shortcuts", "quit"])),
        ]
        ShortcutsDialog(groups, self).exec()

    def _about(self) -> None:
        from frameripper import __version__

        QMessageBox.about(
            self,
            "About FrameRipper",
            f"<b>FrameRipper {__version__}</b><p>Browse video frame by frame, "
            "find the sharpest stills and export them.</p>",
        )
