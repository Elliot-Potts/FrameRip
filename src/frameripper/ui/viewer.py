from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from frameripper.ui import theme

MIN_ZOOM = 0.05
MAX_ZOOM = 32.0
LOUPE_SIZE = 280
LOUPE_ZOOM = 2.0  # physical pixels per source pixel inside the loupe


def to_qimage(arr: np.ndarray) -> QImage:
    h, w, _ = arr.shape
    # QImage borrows the buffer; callers keep arr alive alongside it.
    return QImage(arr.data, w, h, arr.strides[0], QImage.Format_RGB888)


class Viewer(QWidget):
    """Frame canvas with fit / zoom / pan and a pixel loupe.

    Coordinates are in source pixels of the full-resolution frame in display
    orientation, whatever resolution the currently shown image has.
    """

    fullResNeeded = Signal()
    zoomChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMinimumSize(320, 200)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

        self._arr: np.ndarray | None = None
        self._img: QImage | None = None
        self._is_full = False
        self._full_w = self._full_h = 0
        self._full_requested = False

        self._fit = True
        self._scale = 1.0
        self._center = QPointF()
        self._drag_from: QPointF | None = None
        self._drag_center = QPointF()
        self._mouse: QPointF | None = None

        self.loupe = False
        self.capped_ratio = 1.0  # width of screen-capped frames relative to native
        self._badge: str | None = None
        self._message = "Drop a video here\nor press Ctrl+O"
        self._toast: str | None = None
        self._toast_timer = QTimer(self, singleShot=True, timeout=self._clear_toast)

    # -- content ---------------------------------------------------------------

    def set_frame(self, arr: np.ndarray, is_full: bool, full_size: tuple[int, int]) -> None:
        new_video = (self._full_w, self._full_h) != full_size
        self._arr = arr
        self._img = to_qimage(arr)
        self._is_full = is_full
        self._full_w, self._full_h = full_size
        self._message = None
        if new_video:
            self._fit = True
            self._center = QPointF(self._full_w / 2, self._full_h / 2)
            self._emit_zoom()
        self._full_requested = is_full
        self._check_full_res()
        self.update()

    def frame_changed(self) -> None:
        """Called when the shown frame number changes, so full-res is re-requested."""
        self._full_requested = False

    def clear(self, message: str | None = None) -> None:
        self._arr = self._img = None
        self._full_w = self._full_h = 0
        self._message = message
        self._badge = None
        self.update()

    def set_message(self, message: str | None) -> None:
        self._message = message
        self.update()

    def set_badge(self, badge: str | None) -> None:
        if badge != self._badge:
            self._badge = badge
            self.update()

    def toast(self, text: str, ms: int = 2200) -> None:
        self._toast = text
        self._toast_timer.start(ms)
        self.update()

    def _clear_toast(self) -> None:
        self._toast = None
        self.update()

    # -- zoom ------------------------------------------------------------------

    def _dpr(self) -> float:
        return self.devicePixelRatioF()

    def _fit_scale(self) -> float:
        if not self._full_w:
            return 1.0
        return min(self.width() / self._full_w, self.height() / self._full_h)

    def scale(self) -> float:
        return self._fit_scale() if self._fit else self._scale

    def zoom_label(self) -> str:
        pct = round(self.scale() * self._dpr() * 100)
        return f"Fit {pct}%" if self._fit else f"{pct}%"

    def _emit_zoom(self) -> None:
        self.zoomChanged.emit(self.zoom_label())

    def set_fit(self) -> None:
        self._fit = True
        self._center = QPointF(self._full_w / 2, self._full_h / 2)
        self._emit_zoom()
        self.update()

    def set_actual(self, anchor: QPointF | None = None) -> None:
        self._set_scale(1.0 / self._dpr(), anchor)

    def toggle_fit_actual(self, anchor: QPointF | None = None) -> None:
        if self._fit:
            self.set_actual(anchor)
        else:
            self.set_fit()

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        self._set_scale(self.scale() * factor, anchor)

    def _set_scale(self, new_scale: float, anchor: QPointF | None) -> None:
        if not self._full_w:
            return
        new_scale = max(MIN_ZOOM, min(MAX_ZOOM, new_scale))
        old = self.scale()
        if anchor is None:
            anchor = QPointF(self.width() / 2, self.height() / 2)
        wc = QPointF(self.width() / 2, self.height() / 2)
        src = self._view_center() + (anchor - wc) / old
        self._fit = False
        self._scale = new_scale
        self._center = src - (anchor - wc) / new_scale
        self._clamp_center()
        self._emit_zoom()
        self._check_full_res()
        self.update()

    def _view_center(self) -> QPointF:
        if self._fit:
            return QPointF(self._full_w / 2, self._full_h / 2)
        return self._center

    def _clamp_center(self) -> None:
        self._center.setX(max(0.0, min(self._full_w, self._center.x())))
        self._center.setY(max(0.0, min(self._full_h, self._center.y())))

    def _image_rect(self) -> QRectF:
        s = self.scale()
        c = self._view_center()
        w, h = self._full_w * s, self._full_h * s
        x = self.width() / 2 - c.x() * s
        y = self.height() / 2 - c.y() * s
        if self._fit:
            # Snap to whole pixels so fit mode stays crisp.
            x, y = round(x), round(y)
        return QRectF(x, y, w, h)

    def _to_source(self, pos: QPointF) -> QPointF:
        r = self._image_rect()
        s = self.scale()
        return QPointF((pos.x() - r.x()) / s, (pos.y() - r.y()) / s)

    def wants_full_res(self) -> bool:
        """Whether the current zoom or loupe shows more detail than screen-capped frames hold."""
        if self.capped_ratio >= 0.999:
            return False
        return self.loupe or self.scale() * self._dpr() > self.capped_ratio * 1.02

    def needs_full_res(self) -> bool:
        return self._img is not None and not self._is_full and self.wants_full_res()

    def _check_full_res(self) -> None:
        if not self._full_requested and self.needs_full_res():
            self._full_requested = True
            self.fullResNeeded.emit()

    def set_loupe(self, on: bool) -> None:
        self.loupe = on
        self._check_full_res()
        self.update()

    # -- events ----------------------------------------------------------------

    def resizeEvent(self, e) -> None:
        if self._fit:
            self._emit_zoom()
        super().resizeEvent(e)

    def wheelEvent(self, e) -> None:
        if self._img is None:
            return
        steps = e.angleDelta().y() / 120
        if steps:
            self.zoom_by(1.25**steps, e.position())

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self._img is not None and not self._fit:
            self._drag_from = e.position()
            self._drag_center = QPointF(self._center)
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e) -> None:
        self._mouse = e.position()
        if self._drag_from is not None:
            delta = (e.position() - self._drag_from) / self.scale()
            self._center = self._drag_center - delta
            self._clamp_center()
        if self._drag_from is not None or self.loupe:
            self.update()

    def mouseReleaseEvent(self, e) -> None:
        if self._drag_from is not None:
            self._drag_from = None
            self.unsetCursor()

    def mouseDoubleClickEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self._img is not None:
            self.toggle_fit_actual(e.position())

    def leaveEvent(self, e) -> None:
        self._mouse = None
        if self.loupe:
            self.update()

    # -- painting --------------------------------------------------------------

    def paintEvent(self, e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.VIEWER_BG))

        if self._img is not None:
            target = self._image_rect()
            physical = self.scale() * self._dpr() * self._full_w / self._img.width()
            p.setRenderHint(QPainter.SmoothPixmapTransform, physical < 1.0)
            p.drawImage(target, self._img, QRectF(self._img.rect()))
            if self.loupe and self._mouse is not None and target.contains(self._mouse):
                self._paint_loupe(p)
        elif self._message:
            self._paint_message(p, self._message)

        if self._badge:
            self._paint_badge(p)
        if self._toast:
            self._paint_toast(p)
        p.end()

    def _paint_message(self, p: QPainter, text: str) -> None:
        f = QFont(self.font())
        f.setPointSizeF(13)
        p.setFont(f)
        p.setPen(QColor(theme.MUTED))
        r = QRectF(self.rect()).adjusted(40, 40, -40, -40)
        box = QRectF(0, 0, min(420, r.width()), min(200, r.height()))
        box.moveCenter(r.center())
        p.setPen(QPen(QColor(theme.BORDER), 1.5, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(box, 14, 14)
        p.setPen(QColor(theme.MUTED))
        p.drawText(box, Qt.AlignCenter, text)

    def _paint_loupe(self, p: QPainter) -> None:
        dpr = self._dpr()
        size = LOUPE_SIZE
        src_span = size * dpr / LOUPE_ZOOM  # source pixels across the loupe
        src_c = self._to_source(self._mouse)
        ratio = self._img.width() / self._full_w
        src = QRectF(
            (src_c.x() - src_span / 2) * ratio,
            (src_c.y() - src_span / 2) * ratio,
            src_span * ratio,
            src_span * ratio,
        )
        m = self._mouse
        x = m.x() + 24 if m.x() + 24 + size < self.width() else m.x() - 24 - size
        y = max(8.0, min(self.height() - size - 8.0, m.y() - size / 2))
        dest = QRectF(x, y, size, size)

        path = QPainterPath()
        path.addRoundedRect(dest, 10, 10)
        p.save()
        p.setClipPath(path)
        p.fillRect(dest, QColor(theme.VIEWER_BG))
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawImage(dest, self._img, src)
        # Crosshair on the exact source pixel under the cursor.
        p.setPen(QPen(QColor(255, 255, 255, 90), 1))
        p.drawLine(
            QPointF(dest.center().x(), dest.top()), QPointF(dest.center().x(), dest.bottom())
        )
        p.drawLine(
            QPointF(dest.left(), dest.center().y()), QPointF(dest.right(), dest.center().y())
        )
        p.restore()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.ACCENT), 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(dest, 10, 10)
        label = f"{LOUPE_ZOOM:g}x" + ("" if self._is_full else "  loading...")
        p.setPen(QColor(theme.TEXT))
        p.drawText(dest.adjusted(10, 6, -10, -6), Qt.AlignTop | Qt.AlignLeft, label)

    def _paint_badge(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        suggested = self._badge == "Suggested"
        color = QColor(theme.SUGGESTED if suggested else theme.ACCENT)
        text = ("☆ " if suggested else "★ ") + self._badge
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 20
        r = QRectF(self.width() - w - 14, 14, w, 26)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(20, 21, 24, 210))
        p.drawRoundedRect(r, 13, 13)
        p.setPen(color)
        p.drawText(r, Qt.AlignCenter, text)

    def _paint_toast(self, p: QPainter) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        fm = p.fontMetrics()
        text = fm.elidedText(self._toast, Qt.ElideMiddle, self.width() - 80)
        w = fm.horizontalAdvance(text) + 32
        r = QRectF((self.width() - w) / 2, self.height() - 56, w, 34)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(28, 29, 33, 235))
        p.drawRoundedRect(r, 17, 17)
        p.setPen(QColor(theme.TEXT))
        p.drawText(r, Qt.AlignCenter, text)
