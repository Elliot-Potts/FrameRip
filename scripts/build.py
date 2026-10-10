"""Build a standalone FrameRipper app folder with PyInstaller.

uv run --group build python scripts/build.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"


def make_icon() -> Path:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PIL import Image
    from PySide6.QtCore import QBuffer, QIODevice
    from PySide6.QtWidgets import QApplication

    from frameripper.app import app_icon

    _app = QApplication.instance() or QApplication([])
    BUILD.mkdir(exist_ok=True)
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    app_icon().pixmap(256, 256).save(buf, "PNG")
    png = BUILD / "icon.png"
    png.write_bytes(bytes(buf.data()))
    ico = BUILD / "icon.ico"
    Image.open(png).save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
    return ico


def main() -> None:
    import PyInstaller.__main__

    sys.path.insert(0, str(ROOT / "src"))
    ico = make_icon()
    PyInstaller.__main__.run(
        [
            str(ROOT / "src" / "frameripper" / "__main__.py"),
            "--name=FrameRipper",
            "--windowed",
            "--noconfirm",
            f"--icon={ico}",
            f"--paths={ROOT / 'src'}",
            f"--distpath={ROOT / 'dist'}",
            f"--workpath={BUILD / 'pyinstaller'}",
            f"--specpath={BUILD}",
            "--exclude-module=tkinter",
        ]
    )
    # Software OpenGL fallback and Qt translations aren't used.
    internal = ROOT / "dist" / "FrameRipper" / "_internal" / "PySide6"
    (internal / "opengl32sw.dll").unlink(missing_ok=True)
    shutil.rmtree(internal / "translations", ignore_errors=True)


if __name__ == "__main__":
    main()
