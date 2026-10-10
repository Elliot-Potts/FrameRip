import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from clips import write_clip  # noqa: E402


@pytest.fixture(scope="session")
def clip_dir(tmp_path_factory):
    return tmp_path_factory.mktemp("clips")


@pytest.fixture(scope="session")
def h264_clip(clip_dir):
    return write_clip(clip_dir / "h264.mp4", 200)


@pytest.fixture(scope="session")
def mkv_clip(clip_dir):
    return write_clip(clip_dir / "h264.mkv", 150, gop=24)


@pytest.fixture(scope="session")
def hevc_clip(clip_dir):
    return write_clip(clip_dir / "hevc.mp4", 120, codec="libx265", gop=32)


@pytest.fixture(scope="session")
def vfr_clip(clip_dir):
    return write_clip(clip_dir / "vfr.mp4", 120, vfr=True)


@pytest.fixture(scope="session")
def rotated_clip(clip_dir):
    return write_clip(clip_dir / "rot.mp4", 40, rotation=90)
