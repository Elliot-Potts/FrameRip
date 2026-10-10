"""Small vector icons drawn with QPainter so they stay crisp at any DPI."""

from __future__ import annotations

import math
from functools import cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPen, QPixmap

from frameripper.ui import theme

SIZE = 24


def _tri(path: QPainterPath, x: float, pointing_right: bool, w: float = 7.0) -> None:
    if pointing_right:
        path.moveTo(x, 6)
        path.lineTo(x + w, 12)
        path.lineTo(x, 18)
    else:
        path.moveTo(x + w, 6)
        path.lineTo(x, 12)
        path.lineTo(x + w, 18)
    path.closeSubpath()


def _star(cx: float, cy: float, r: float) -> QPainterPath:
    path = QPainterPath()
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.45
        a = -math.pi / 2 + i * math.pi / 5
        p = QPointF(cx + rad * math.cos(a), cy + rad * math.sin(a))
        path.moveTo(p) if i == 0 else path.lineTo(p)
    path.closeSubpath()
    return path


def _draw(name: str, p: QPainter, color: QColor) -> None:
    fill = QPainterPath()
    pen = QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    stroke = QPainterPath()

    if name == "play":
        fill.moveTo(8, 5)
        fill.lineTo(19, 12)
        fill.lineTo(8, 19)
        fill.closeSubpath()
    elif name == "pause":
        fill.addRoundedRect(QRectF(7, 5, 3.5, 14), 1, 1)
        fill.addRoundedRect(QRectF(13.5, 5, 3.5, 14), 1, 1)
    elif name == "next_frame":
        _tri(fill, 8, True)
        fill.addRect(QRectF(16, 6, 2, 12))
    elif name == "prev_frame":
        _tri(fill, 9, False)
        fill.addRect(QRectF(6, 6, 2, 12))
    elif name == "next_second":
        _tri(fill, 5, True)
        _tri(fill, 12, True)
    elif name == "prev_second":
        _tri(fill, 5, False)
        _tri(fill, 12, False)
    elif name == "first":
        _tri(fill, 9, False)
        _tri(fill, 15, False, 5)
        fill.addRect(QRectF(5, 6, 2, 12))
    elif name == "last":
        _tri(fill, 4, True, 5)
        _tri(fill, 9, True)
        fill.addRect(QRectF(17, 6, 2, 12))
    elif name == "mark":
        stroke = _star(12, 12.5, 8)
    elif name == "marked":
        fill = _star(12, 12.5, 8)
    elif name == "peak_next":
        stroke.moveTo(3, 18)
        stroke.lineTo(8, 18)
        stroke.lineTo(11, 7)
        stroke.lineTo(14, 18)
        fill.moveTo(15, 9)
        fill.lineTo(21, 12.5)
        fill.lineTo(15, 16)
        fill.closeSubpath()
    elif name == "peak_prev":
        stroke.moveTo(21, 18)
        stroke.lineTo(16, 18)
        stroke.lineTo(13, 7)
        stroke.lineTo(10, 18)
        fill.moveTo(9, 9)
        fill.lineTo(3, 12.5)
        fill.lineTo(9, 16)
        fill.closeSubpath()
    elif name == "export":
        stroke.moveTo(12, 4)
        stroke.lineTo(12, 14)
        stroke.moveTo(8, 10.5)
        stroke.lineTo(12, 14.5)
        stroke.lineTo(16, 10.5)
        stroke.moveTo(5, 15)
        stroke.lineTo(5, 19)
        stroke.lineTo(19, 19)
        stroke.lineTo(19, 15)
    elif name == "open":
        stroke.moveTo(4, 18)
        stroke.lineTo(4, 6)
        stroke.lineTo(9, 6)
        stroke.lineTo(11, 8)
        stroke.lineTo(19, 8)
        stroke.lineTo(19, 10)
        stroke.moveTo(4, 18)
        stroke.lineTo(7, 11)
        stroke.lineTo(21, 11)
        stroke.lineTo(18, 18)
        stroke.closeSubpath()
    elif name == "loupe":
        stroke.addEllipse(QPointF(10.5, 10.5), 5.5, 5.5)
        stroke.moveTo(14.5, 14.5)
        stroke.lineTo(19.5, 19.5)
    elif name == "fit":
        for sx, sy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
            cx, cy = 12 + sx * 7, 12 + sy * 7
            stroke.moveTo(cx, cy - sy * 4)
            stroke.lineTo(cx, cy)
            stroke.lineTo(cx - sx * 4, cy)
    elif name == "actual":
        stroke.addRoundedRect(QRectF(4, 6, 16, 12), 2, 2)
        stroke.moveTo(9, 10)
        stroke.lineTo(10, 9.5)
        stroke.lineTo(10, 15)
        stroke.moveTo(14, 10)
        stroke.lineTo(15, 9.5)
        stroke.lineTo(15, 15)
    elif name == "auto":
        stroke = _star(9, 10, 5)
        fill = _star(17, 16, 4)
    elif name == "clipboard":
        stroke.addRoundedRect(QRectF(6, 5, 12, 15), 2, 2)
        stroke.moveTo(9, 5)
        stroke.lineTo(9, 3.5)
        stroke.lineTo(15, 3.5)
        stroke.lineTo(15, 5)

    if not stroke.isEmpty():
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(stroke)
    if not fill.isEmpty():
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawPath(fill)


def _pixmap(name: str, color: QColor, scale: int) -> QPixmap:
    img = QImage(SIZE * scale, SIZE * scale, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(scale, scale)
    _draw(name, p, color)
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(scale)
    return pm


@cache
def icon(name: str, accent: bool = False) -> QIcon:
    base = QColor(theme.ACCENT if accent else theme.TEXT)
    muted = QColor(theme.MUTED)
    ic = QIcon()
    for scale in (1, 2, 3):
        ic.addPixmap(_pixmap(name, base, scale), QIcon.Normal)
        ic.addPixmap(_pixmap(name, muted, scale), QIcon.Disabled)
    return ic
