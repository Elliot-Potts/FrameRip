from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from frameripper.analysis.data import Analysis
from frameripper.marks import Marks
from frameripper.ui import theme

MARGIN = 14
HEAT_H = 12
MARK_ZONE = 10


class Timeline(QWidget):
    """Scrubber with the sharpness heatmap, marks and playhead."""

    seekRequested = Signal(int)
    stepRequested = Signal(int)
    hovered = Signal(int, QPoint)  # frame, global position of the playhead top; -1 on leave

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(46)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self._count = 0
        self._pos = 0
        self._hover: int | None = None
        self._dragging = False
        self._analysis: Analysis | None = None
        self._marks: Marks | None = None
        self._heat: QImage | None = None
        self._heat_buf: np.ndarray | None = None
        self._heat_key = None

    def set_video(self, frame_count: int) -> None:
        self._count = frame_count
        self._pos = 0
        self._heat_key = None
        self.update()

    def set_position(self, n: int) -> None:
        if n != self._pos:
            self._pos = n
            self.update()

    def set_analysis(self, analysis: Analysis | None) -> None:
        self._analysis = analysis
        self.update()

    def set_marks(self, marks: Marks | None) -> None:
        self._marks = marks
        self.update()

    # -- geometry ----------------------------------------------------------------

    def _track(self) -> QRectF:
        return QRectF(MARGIN, 8, self.width() - 2 * MARGIN, self.height() - 16)

    def _x_of(self, n: float) -> float:
        t = self._track()
        if self._count <= 1:
            return t.left()
        return t.left() + n / (self._count - 1) * t.width()

    def _frame_at(self, x: float) -> int:
        t = self._track()
        if self._count <= 1 or t.width() <= 0:
            return 0
        f = (x - t.left()) / t.width() * (self._count - 1)
        return int(max(0, min(self._count - 1, round(f))))

    # -- events ----------------------------------------------------------------

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self._count:
            self._dragging = True
            self.seekRequested.emit(self._frame_at(e.position().x()))

    def mouseMoveEvent(self, e) -> None:
        if not self._count:
            return
        n = self._frame_at(e.position().x())
        if self._dragging:
            self.seekRequested.emit(n)
        if n != self._hover:
            self._hover = n
            self.update()
            anchor = self.mapToGlobal(QPoint(round(self._x_of(n)), 0))
            self.hovered.emit(n, anchor)

    def mouseReleaseEvent(self, e) -> None:
        self._dragging = False

    def leaveEvent(self, e) -> None:
        self._hover = None
        self.hovered.emit(-1, QPoint())
        self.update()

    def wheelEvent(self, e) -> None:
        steps = round(e.angleDelta().y() / 120)
        if steps:
            self.stepRequested.emit(-steps)

    # -- painting --------------------------------------------------------------

    def _heat_image(self, width: int) -> QImage | None:
        a = self._analysis
        if a is None or width <= 0 or self._count == 0:
            return None
        key = (a.version, width, self._count)
        if key == self._heat_key:
            return self._heat
        norm = np.nan_to_num(a.normalised(), nan=-1.0)
        # Each pixel column shows the best frame inside it, so sharp moments
        # don't get averaged away on long videos.
        edges = np.linspace(0, self._count, width + 1).astype(np.int64)
        edges = np.minimum(edges, self._count - 1)
        starts = edges[:-1]
        col = np.maximum.reduceat(norm, starts)
        rgb = np.empty((1, width, 3), np.uint8)
        valid = col >= 0
        rgb[0, valid] = theme.HEAT[(np.clip(col[valid], 0, 1) * 255).astype(np.int64)]
        rgb[0, ~valid] = theme.HEAT_NONE
        self._heat_buf = np.ascontiguousarray(rgb)
        self._heat = QImage(self._heat_buf.data, width, 1, width * 3, QImage.Format_RGB888)
        self._heat_key = key
        return self._heat

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.SURFACE))
        if not self._count:
            p.end()
            return
        t = self._track()
        heat_rect = QRectF(t.left(), t.top() + 2, t.width(), HEAT_H)

        p.setRenderHint(QPainter.Antialiasing)
        clip = QPainterPath()
        clip.addRoundedRect(heat_rect, 3, 3)
        p.save()
        p.setClipPath(clip)
        img = self._heat_image(int(t.width()))
        if img is not None:
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.drawImage(heat_rect, img, QRectF(0, 0, img.width(), 1))
        else:
            p.fillRect(heat_rect, QColor(*theme.HEAT_NONE))
        p.restore()

        # Played portion indicator under the heatmap.
        rail = QRectF(t.left(), heat_rect.bottom() + 5, t.width(), 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.BORDER))
        p.drawRoundedRect(rail, 1.5, 1.5)
        played = QRectF(rail)
        played.setRight(self._x_of(self._pos))
        p.setBrush(QColor(theme.ACCENT).darker(160))
        p.drawRoundedRect(played, 1.5, 1.5)

        if self._marks is not None:
            mark_y = rail.bottom() + 3
            for frames, color, filled in (
                (self._marks.suggested, theme.SUGGESTED, False),
                (self._marks.marked, theme.ACCENT, True),
            ):
                c = QColor(color)
                p.setPen(QPen(c, 1.2) if not filled else Qt.NoPen)
                p.setBrush(c if filled else Qt.NoBrush)
                for n in frames:
                    x = self._x_of(n)
                    tri = QPainterPath()
                    tri.moveTo(x, mark_y)
                    tri.lineTo(x + 4, mark_y + 6)
                    tri.lineTo(x - 4, mark_y + 6)
                    tri.closeSubpath()
                    p.drawPath(tri)

        if self._hover is not None and not self._dragging:
            x = self._x_of(self._hover)
            p.setPen(QPen(QColor(255, 255, 255, 70), 1))
            p.drawLine(QPointF(x, t.top()), QPointF(x, t.bottom()))

        x = self._x_of(self._pos)
        p.setPen(QPen(QColor(theme.ACCENT), 2))
        p.drawLine(QPointF(x, t.top() - 2), QPointF(x, t.bottom()))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(QPointF(x, t.top() - 1), 4.5, 4.5)
        p.end()
