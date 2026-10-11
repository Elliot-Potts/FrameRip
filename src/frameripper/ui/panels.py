from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from frameripper.analysis.data import Analysis
from frameripper.export.naming import display_timecode
from frameripper.marks import Marks
from frameripper.ui import theme
from frameripper.ui.viewer import to_qimage
from frameripper.ui.workers import ThumbThread
from frameripper.video.index import FrameIndex


class HoverPreview(QWidget):
    """Floating thumbnail shown above the timeline while hovering."""

    def __init__(self, parent: QWidget):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._arr = None
        self._text = ""
        self._thumb_size = QSize(160, 90)

    def show_at(self, anchor: QPoint, arr, text: str, thumb_size: QSize) -> None:
        self._arr = arr
        self._text = text
        self._thumb_size = thumb_size
        w, h = thumb_size.width() + 8, thumb_size.height() + 28
        self.resize(w, h)
        self.move(anchor.x() - w // 2, anchor.y() - h - 6)
        if not self.isVisible():
            self.show()
        self.update()

    def set_image(self, arr) -> None:
        self._arr = arr
        self.update()

    def paintEvent(self, e) -> None:
        with QPainter(self) as p:
            self._paint(p)

    def _paint(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(theme.BORDER))
        p.setBrush(QColor(theme.RAISED))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
        img_rect = QRectF(4, 4, self._thumb_size.width(), self._thumb_size.height())
        if self._arr is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(img_rect, to_qimage(self._arr))
        else:
            p.fillRect(img_rect, QColor(theme.BG))
        p.setPen(QColor(theme.TEXT))
        p.drawText(QRectF(0, img_rect.bottom() + 2, self.width(), 20), Qt.AlignCenter, self._text)


class MarksPanel(QWidget):
    """List of marked and suggested frames with actions."""

    seekRequested = Signal(int)
    changed = Signal()
    exportRequested = Signal()
    autoPickRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._index: FrameIndex | None = None
        self._marks: Marks | None = None
        self._analysis: Analysis | None = None
        self._thumbs: ThumbThread | None = None

        self.list = QListWidget()
        self.list.setIconSize(QSize(112, 63))
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.setTextElideMode(Qt.ElideRight)
        self.list.itemActivated.connect(self._activated)
        self.list.itemClicked.connect(self._activated)
        self.list.itemSelectionChanged.connect(self._update_buttons)

        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.empty = QLabel(
            "Press M to mark the current frame,\nor use Auto-pick to suggest stills."
        )
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignCenter)
        self.empty.setWordWrap(True)

        self.accept_btn = QPushButton("Accept")
        self.accept_btn.setToolTip("Turn the selected suggestions into marks")
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.setToolTip("Remove the selected marks (Delete)")
        self.accept_all_btn = QPushButton("Accept all")
        self.clear_sugg_btn = QPushButton("Clear suggestions")
        self.auto_btn = QPushButton("Auto-pick...")
        self.export_btn = QPushButton("Export marked...")
        self.export_btn.setObjectName("Primary")

        self.accept_btn.clicked.connect(self._accept_selected)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.accept_all_btn.clicked.connect(self._accept_all)
        self.clear_sugg_btn.clicked.connect(self._clear_suggestions)
        self.auto_btn.clicked.connect(self.autoPickRequested)
        self.export_btn.clicked.connect(self.exportRequested)

        for b in (
            self.accept_btn,
            self.remove_btn,
            self.accept_all_btn,
            self.clear_sugg_btn,
            self.auto_btn,
            self.export_btn,
        ):
            b.setFocusPolicy(Qt.NoFocus)

        row1 = QHBoxLayout()
        row1.addWidget(self.accept_btn)
        row1.addWidget(self.remove_btn)
        row2 = QHBoxLayout()
        row2.addWidget(self.accept_all_btn)
        row2.addWidget(self.clear_sugg_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        layout.addWidget(self.summary)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.empty, 1)
        layout.addLayout(row1)
        layout.addLayout(row2)
        layout.addWidget(self.auto_btn)
        layout.addWidget(self.export_btn)
        self.setMinimumWidth(250)
        self.refresh()

    def set_source(self, index, marks, analysis, thumbs) -> None:
        if self._thumbs is not None:
            try:
                self._thumbs.thumbReady.disconnect(self._on_thumb)
            except (RuntimeError, TypeError):
                pass
        self._index, self._marks, self._analysis, self._thumbs = index, marks, analysis, thumbs
        if thumbs is not None:
            thumbs.thumbReady.connect(self._on_thumb)
        self.refresh()

    def _icon(self, n: int, suggested: bool) -> QIcon:
        arr = self._thumbs.thumb(n) if self._thumbs is not None else None
        size = self.list.iconSize()
        pm = QPixmap(size)
        pm.fill(QColor(theme.RAISED))
        with QPainter(pm) as p:
            if arr is not None:
                img = to_qimage(arr)
                s = min(size.width() / img.width(), size.height() / img.height())
                target = QRectF(0, 0, img.width() * s, img.height() * s)
                target.moveCenter(QRectF(pm.rect()).center())
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawImage(target, img)
            p.setPen(QColor(theme.SUGGESTED if suggested else theme.ACCENT))
            p.drawRect(QRectF(pm.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        return QIcon(pm)

    def refresh(self) -> None:
        selected = {it.data(Qt.UserRole) for it in self.list.selectedItems()}
        self.list.clear()
        has = self._marks is not None and bool(self._marks.all())
        self.list.setVisible(has)
        self.empty.setVisible(not has)
        if self._marks is None or self._index is None:
            self.summary.setText("No video loaded")
            self._update_buttons()
            return
        for n in self._marks.all():
            suggested = self._marks.is_suggested(n)
            score = self._analysis.score(n) if self._analysis is not None else None
            score_txt = f"sharp {score:.0f}" if score is not None else "sharp --"
            text = f"Frame {n}\n{display_timecode(self._index.time_of(n))}\n{score_txt}"
            if suggested:
                text += "  • suggested"
            item = QListWidgetItem(self._icon(n, suggested), text)
            item.setData(Qt.UserRole, n)
            if suggested:
                item.setForeground(QColor(theme.SUGGESTED))
            self.list.addItem(item)
            if n in selected:
                item.setSelected(True)
        m = self._marks
        self.summary.setText(f"{len(m.marked)} marked · {len(m.suggested)} suggested")
        if self._thumbs is not None:
            self._thumbs.want("marks", m.all())
        self._update_buttons()

    def _on_thumb(self, n: int) -> None:
        for i in range(self.list.count()):
            item = self.list.item(i)
            if item.data(Qt.UserRole) == n:
                item.setIcon(self._icon(n, self._marks.is_suggested(n)))
                break

    def _selected_frames(self) -> list[int]:
        return [it.data(Qt.UserRole) for it in self.list.selectedItems()]

    def _update_buttons(self) -> None:
        m = self._marks
        sel = self._selected_frames()
        self.accept_btn.setEnabled(m is not None and any(m.is_suggested(n) for n in sel))
        self.remove_btn.setEnabled(bool(sel))
        self.accept_all_btn.setEnabled(m is not None and bool(m.suggested))
        self.clear_sugg_btn.setEnabled(m is not None and bool(m.suggested))
        self.export_btn.setEnabled(m is not None and bool(m.marked))
        self.auto_btn.setEnabled(m is not None)

    def _activated(self, item: QListWidgetItem) -> None:
        self.seekRequested.emit(item.data(Qt.UserRole))

    def _accept_selected(self) -> None:
        self._marks.accept(self._selected_frames())
        self.changed.emit()

    def remove_selected(self) -> None:
        for n in self._selected_frames():
            self._marks.remove(n)
        self.changed.emit()

    def _accept_all(self) -> None:
        self._marks.accept_all()
        self.changed.emit()

    def _clear_suggestions(self) -> None:
        self._marks.clear_suggestions()
        self.changed.emit()
