from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from frameripper.export.exporter import (
    ExportItem,
    ExportOptions,
    ExportResult,
    decode_full,
    export_frames,
)
from frameripper.video.cache import FrameCache
from frameripper.video.decoder import DecodeAborted, FrameDecoder, scaled_size, to_rgb
from frameripper.video.index import FrameIndex, VideoOpenError, build_index

log = logging.getLogger(__name__)


class IndexThread(QThread):
    loaded = Signal(object)  # FrameIndex
    failed = Signal(str)

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.path = path

    def run(self) -> None:
        try:
            self.loaded.emit(build_index(self.path))
        except VideoOpenError as e:
            self.failed.emit(str(e))
        except Exception as e:
            log.exception("indexing failed")
            self.failed.emit(f"Could not open {Path(self.path).name}: {e}")


class DecodeThread(QThread):
    """Serves frames for the viewer. Only the newest request matters.

    Keys are (frame, full) where full means native resolution rather than
    screen-capped.
    """

    frameReady = Signal(int, bool, object)  # frame, full, ndarray

    def __init__(self, index: FrameIndex, max_size: tuple[int, int], budget: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.max_w, self.max_h = max_size
        self.cache = FrameCache(budget)
        self._cond = threading.Condition()
        self._pending: tuple[int, bool] | None = None
        self._stop = False
        self._last_target = -1

    def cached(self, n: int, full: bool = False) -> np.ndarray | None:
        arr = self.cache.get((n, full))
        if arr is None and not full:
            # A full-res frame is a fine stand-in when it is all we have.
            arr = self.cache.get((n, True))
        return arr

    def request(self, n: int, full: bool = False) -> None:
        with self._cond:
            self._pending = (n, full)
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()

    def _convert(self, frame, full: bool) -> np.ndarray:
        if full:
            return to_rgb(frame, self.index, quality=True)
        return to_rgb(frame, self.index, self.max_w, self.max_h)

    def run(self) -> None:
        dec = FrameDecoder(self.index)
        try:
            while True:
                with self._cond:
                    while self._pending is None and not self._stop:
                        self._cond.wait()
                    if self._stop:
                        return
                    key = self._pending
                    self._pending = None
                self._serve(dec, key)
        finally:
            dec.close()

    def _serve(self, dec: FrameDecoder, key: tuple[int, bool]) -> None:
        n, full = key
        arr = self.cache.get(key)
        if arr is not None:
            self.frameReady.emit(n, full, arr)
            return

        # Stepping backwards: keep frames decoded on the way through the GOP so
        # the next few Left presses are instant. Only as many as the cache can
        # comfortably hold, or big frames would evict each other.
        backward = n < self._last_target
        self._last_target = n
        if full:
            w, h = self.index.display_size
        else:
            w, h = scaled_size(self.index, self.max_w, self.max_h)
        keep_from = n - max(1, self.cache.budget // (w * h * 3 * 2))

        def passed(i: int, frame) -> None:
            if backward and i >= keep_from and (i, full) not in self.cache:
                self.cache.put((i, full), self._convert(frame, full))

        def should_abort() -> bool:
            p = self._pending
            if p is None or p == key or self._stop:
                return self._stop
            # A request for a frame still ahead of us on this pass will be
            # cached anyway, so finish rather than restart.
            return not (backward and p[1] == full and max(dec.position, keep_from) < p[0] <= n)

        t0 = time.perf_counter()
        try:
            frame = dec.get(n, on_passed=passed, should_abort=should_abort)
        except DecodeAborted:
            return
        except (EOFError, Exception) as e:
            log.warning("decode of frame %d failed: %s", n, e)
            return
        arr = self._convert(frame, full)
        self.cache.put(key, arr)
        log.debug(
            "frame %d%s in %.1f ms", n, " full" if full else "", (time.perf_counter() - t0) * 1e3
        )
        self.frameReady.emit(n, full, arr)


class ThumbThread(QThread):
    """Small thumbnails for the filmstrip, marks list and timeline hover.

    Each consumer sets a list of wanted frames on its own channel; earlier
    channels win.
    """

    thumbReady = Signal(int)

    CHANNELS = ("preview", "filmstrip", "marks")

    def __init__(self, index: FrameIndex, height: int, budget: int, parent=None):
        super().__init__(parent)
        self.index = index
        self.height = height
        dw, dh = index.display_size
        self.width = max(2, round(height * dw / dh))
        self.cache = FrameCache(budget)
        self._cond = threading.Condition()
        self._wanted: dict[str, list[int]] = {c: [] for c in self.CHANNELS}
        self._generation = 0
        self._stop = False

    def thumb(self, n: int) -> np.ndarray | None:
        return self.cache.get(n)

    def want(self, channel: str, frames: list[int]) -> None:
        with self._cond:
            if self._wanted[channel] == frames:
                return
            self._wanted[channel] = list(frames)
            self._generation += 1
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()

    def _next_job(self) -> int | None:
        for channel in self.CHANNELS:
            for n in self._wanted[channel]:
                if n not in self.cache:
                    return n
        return None

    def _convert(self, frame) -> np.ndarray:
        return to_rgb(frame, self.index, self.width, self.height)

    def run(self) -> None:
        dec = FrameDecoder(self.index)
        try:
            while True:
                with self._cond:
                    while not self._stop and (job := self._next_job()) is None:
                        self._cond.wait()
                    if self._stop:
                        return
                    generation = self._generation
                    wanted = set().union(*self._wanted.values())

                def passed(i: int, frame, wanted=wanted) -> None:
                    if i in wanted and i not in self.cache:
                        self.cache.put(i, self._convert(frame))
                        self.thumbReady.emit(i)

                try:
                    frame = dec.get(
                        job,
                        on_passed=passed,
                        should_abort=lambda g=generation: self._stop or self._generation != g,
                    )
                except DecodeAborted:
                    continue
                except Exception as e:
                    log.warning("thumbnail %d failed: %s", job, e)
                    # Don't retry a broken frame forever.
                    self.cache.put(job, np.zeros((self.height, self.width, 3), np.uint8))
                    continue
                self.cache.put(job, self._convert(frame))
                self.thumbReady.emit(job)
        finally:
            dec.close()


class _ExportSignals(QObject):
    progress = Signal(int, int)
    done = Signal(object)  # ExportResult
    frame = Signal(object)  # ndarray, for clipboard jobs


class ExportTask(QRunnable):
    def __init__(self, index: FrameIndex, items: list[ExportItem], opts: ExportOptions):
        super().__init__()
        self.index, self.items, self.opts = index, items, opts
        self.signals = _ExportSignals()
        self.cancel_requested = False

    def run(self) -> None:
        try:
            result = export_frames(
                self.index,
                self.items,
                self.opts,
                progress=self.signals.progress.emit,
                cancelled=lambda: self.cancel_requested,
            )
        except Exception as e:
            log.exception("export failed")
            result = ExportResult(errors=[str(e)])
        self.signals.done.emit(result)


class FullFrameTask(QRunnable):
    """Decodes one frame at native resolution (used for copy to clipboard)."""

    def __init__(self, index: FrameIndex, n: int):
        super().__init__()
        self.index, self.n = index, n
        self.signals = _ExportSignals()

    def run(self) -> None:
        try:
            with FrameDecoder(self.index) as dec:
                self.signals.frame.emit(decode_full(dec, self.n))
        except Exception as e:
            log.warning("full frame decode failed: %s", e)
            self.signals.frame.emit(None)
