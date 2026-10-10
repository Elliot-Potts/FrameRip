from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from frameripper.analysis.data import Analysis
from frameripper.marks import Marks
from frameripper.ui import theme
from frameripper.ui.viewer import to_qimage
from frameripper.ui.workers import ThumbThread

GAP = 6
PAD = 8
LABEL_H = 14
BAR_H = 3


class Filmstrip(QWidget):
    """Neighbouring frames around the playhead, centred on the current one."""

    seekRequested = Signal(int)
    stepRequested = Signal(int)

    THUMB_H = 64

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(self.THUMB_H + 2 * PAD + LABEL_H + BAR_H + 4)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self._thumbs: ThumbThread | None = None
        self._count = 0
        self._pos = 0
        self.step = 1
        self._aspect = 16 / 9
        self._analysis: Analysis | None = None
        self._marks: Marks | None = None
        self._slots: list[tuple[QRectF, int]] = []
        self._hover: int | None = None

    def set_source(self, thumbs: ThumbThread | None, frame_count: int, aspect: float) -> None:
        if self._thumbs is not None:
            try:
                self._thumbs.thumbReady.disconnect(self._on_thumb)
            except (RuntimeError, TypeError):
                pass
        self._thumbs = thumbs
        self._count = frame_count
        self._aspect = aspect
        self._pos = 0
        if thumbs is not None:
            thumbs.thumbReady.connect(self._on_thumb)
        self._relayout()

    def set_position(self, n: int) -> None:
        if n != self._pos:
            self._pos = n
            self._relayout()

    def set_step(self, step: int) -> None:
        self.step = max(1, step)
        self._relayout()

    def set_analysis(self, analysis: Analysis | None) -> None:
        self._analysis = analysis
        self.update()

    def set_marks(self, marks: Marks | None) -> None:
        self._marks = marks
        self.update()

    def visible_frames(self) -> list[int]:
        return [n for _, n in self._slots]

    def _relayout(self) -> None:
        self._slots = []
        if self._count:
            th = self.THUMB_H
            tw = max(24, round(th * self._aspect))
            slots = max(1, (self.width() - PAD) // (tw + GAP))
            if slots % 2 == 0:
                slots -= 1
            mid = slots // 2
            total = slots * (tw + GAP) - GAP
            x0 = (self.width() - total) / 2
            for i in range(slots):
                n = self._pos + (i - mid) * self.step
                if 0 <= n < self._count:
                    self._slots.append((QRectF(x0 + i * (tw + GAP), PAD, tw, th), n))
        if self._thumbs is not None:
            # Nearest first so the frames you're looking at fill in first.
            order = sorted(self.visible_frames(), key=lambda n: abs(n - self._pos))
            self._thumbs.want("filmstrip", order)
        self.update()

    def _on_thumb(self, n: int) -> None:
        if any(n == f for _, f in self._slots):
            self.update()

    def resizeEvent(self, e) -> None:
        self._relayout()
        super().resizeEvent(e)

    def _slot_at(self, pos: QPointF) -> int | None:
        for rect, n in self._slots:
            if rect.adjusted(-GAP / 2, -PAD, GAP / 2, PAD + LABEL_H).contains(pos):
                return n
        return None

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton:
            n = self._slot_at(e.position())
            if n is not None:
                self.seekRequested.emit(n)

    def mouseMoveEvent(self, e) -> None:
        n = self._slot_at(e.position())
        if n != self._hover:
            self._hover = n
            self.setCursor(Qt.PointingHandCursor if n is not None else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e) -> None:
        self._hover = None
        self.update()

    def wheelEvent(self, e) -> None:
        steps = round(e.angleDelta().y() / 120)
        if steps:
            self.stepRequested.emit(-steps * self.step)

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.SURFACE))
        p.setRenderHint(QPainter.Antialiasing)
        small = QFont(self.font())
        small.setPointSizeF(7.5)
        p.setFont(small)
        norm = self._analysis.normalised() if self._analysis is not None else None

        for rect, n in self._slots:
            current = n == self._pos
            arr = self._thumbs.thumb(n) if self._thumbs is not None else None
            if arr is not None:
                p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                p.drawImage(rect, to_qimage(arr))
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(theme.RAISED))
                p.drawRoundedRect(rect, 3, 3)
            if not current:
                # Dim neighbours a touch so the current frame stands out.
                p.fillRect(rect, QColor(0, 0, 0, 40 if n == self._hover else 90))

            bar = QRectF(rect.left(), rect.bottom() + 3, rect.width(), BAR_H)
            p.setPen(Qt.NoPen)
            p.setBrush(theme.heat_color(None if norm is None else float(norm[n])))
            p.drawRoundedRect(bar, 1.5, 1.5)

            label_rect = QRectF(rect.left(), bar.bottom() + 1, rect.width(), LABEL_H)
            p.setPen(QColor(theme.TEXT if current else theme.MUTED))
            p.drawText(label_rect, Qt.AlignCenter, str(n))

            if self._marks is not None:
                if self._marks.is_marked(n):
                    self._star(p, rect, theme.ACCENT, True)
                elif self._marks.is_suggested(n):
                    self._star(p, rect, theme.SUGGESTED, False)

            if current:
                p.setPen(QPen(QColor(theme.ACCENT), 2))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(rect.adjusted(-1, -1, 1, 1), 3, 3)
        p.end()

    def _star(self, p: QPainter, rect: QRectF, color: str, filled: bool) -> None:
        r = QRectF(rect.right() - 17, rect.top() + 3, 14, 14)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawEllipse(r)
        p.setPen(QColor(color))
        p.drawText(r, Qt.AlignCenter, "★" if filled else "☆")

    def anchor_for(self, n: int) -> QPoint | None:
        for rect, f in self._slots:
            if f == n:
                return self.mapToGlobal(rect.center().toPoint())
        return None
