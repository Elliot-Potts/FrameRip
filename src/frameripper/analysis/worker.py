from __future__ import annotations

import time

import av
from PySide6.QtCore import QThread, Signal

from frameripper.analysis import sharpness as sh
from frameripper.analysis.data import Analysis
from frameripper.video.decoder import to_gray
from frameripper.video.index import FrameIndex


class AnalysisThread(QThread):
    """Decodes every frame once, in order, filling in an Analysis as it goes."""

    progressed = Signal(int)  # frames analysed so far
    completed = Signal()
    failed = Signal(str)

    EMIT_INTERVAL = 0.25

    def __init__(self, index: FrameIndex, analysis: Analysis, parent=None):
        super().__init__(parent)
        self.index = index
        self.analysis = analysis
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        a = self.analysis
        width = min(sh.ANALYSIS_WIDTH, self.index.width)
        prev_small = None
        prev_hist = None
        done = 0
        last_emit = time.monotonic()
        try:
            with av.open(self.index.path) as container:
                stream = container.streams.video[0]
                stream.thread_type = "AUTO"
                n = -1
                for frame in container.decode(stream):
                    if self._stop:
                        return
                    n = self.index.frame_of_pts(frame.pts) if frame.pts is not None else n + 1
                    gray = to_gray(frame, width)
                    tiny = sh.small(gray)
                    hist = sh.histogram(tiny)
                    a.sharpness[n] = sh.tile_sharpness(gray)
                    a.motion[n] = sh.motion(prev_small, tiny)
                    a.change[n] = sh.hist_change(prev_hist, hist)
                    prev_small, prev_hist = tiny, hist
                    done += 1
                    now = time.monotonic()
                    if now - last_emit >= self.EMIT_INTERVAL:
                        last_emit = now
                        a.version += 1
                        self.progressed.emit(done)
        except av.error.FFmpegError as e:
            # Keep whatever was analysed; the gaps just stay unscored.
            a.version += 1
            self.progressed.emit(done)
            self.failed.emit(str(e))
            return

        if self._stop:
            return
        a.version += 1
        a.complete = True
        self.progressed.emit(done)
        self.completed.emit()
