from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QSettings, QStandardPaths, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QApplication

from frameripper.analysis.store import Store
from frameripper.ui import theme
from frameripper.ui.main_window import MainWindow


def app_icon() -> QIcon:
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        s = size / 32
        p.scale(s, s)
        body = QPainterPath()
        body.addRoundedRect(2, 5, 28, 22, 5, 5)
        p.fillPath(body, QColor(theme.RAISED))
        # Film perforations
        p.setBrush(QColor(theme.BG))
        p.setPen(Qt.NoPen)
        for x in (5, 11, 17, 23):
            p.drawRoundedRect(x, 7, 4, 3, 1, 1)
            p.drawRoundedRect(x, 22, 4, 3, 1, 1)
        frame = QPainterPath()
        frame.addRoundedRect(8, 12, 16, 8, 1.5, 1.5)
        p.fillPath(frame, QColor(theme.ACCENT))
        p.end()
        ic.addPixmap(QPixmap.fromImage(img))
    return ic


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("FRAMERIPPER_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv)
    app.setApplicationName("FrameRipper")
    app.setOrganizationName("FrameRipper")
    app.setWindowIcon(app_icon())
    theme.apply(app)

    settings = QSettings()
    data_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppDataLocation))
    store = Store(data_dir / "videos")

    win = MainWindow(settings, store)
    win.show()

    files = [a for a in argv[1:] if not a.startswith("-")]
    if files:
        win.open_video(files[0])
    return app.exec()
