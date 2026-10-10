import random

import numpy as np
import pytest
from clips import read_number

from frameripper.video.decoder import FrameDecoder, to_rgb
from frameripper.video.index import VideoOpenError, build_index


@pytest.fixture(params=["h264_clip", "mkv_clip", "hevc_clip", "vfr_clip"])
def clip(request):
    return request.getfixturevalue(request.param)


def number_of(frame, index):
    return read_number(to_rgb(frame, index))


def test_index_counts_every_frame(h264_clip):
    index = build_index(h264_clip)
    assert index.frame_count == 200
    assert index.keyframes[0] == 0
    assert list(index.keyframes[:3]) == [0, 30, 60]
    assert index.avg_fps == pytest.approx(30, rel=0.01)
    assert index.time_of(30) == pytest.approx(1.0)
    assert index.frame_at_time(1.0) == 30


def test_vfr_timestamps(vfr_clip):
    index = build_index(vfr_clip)
    assert index.frame_count == 120
    gaps = np.diff(index.pts)
    assert len(set(gaps.tolist())) > 1


def test_forward_sequence(clip):
    index = build_index(clip)
    with FrameDecoder(index) as dec:
        for n in range(index.frame_count):
            assert number_of(dec.get(n), index) == n


def test_backward_sequence(clip):
    index = build_index(clip)
    with FrameDecoder(index) as dec:
        for n in range(index.frame_count - 1, -1, -1):
            assert number_of(dec.get(n), index) == n


def test_random_access(clip):
    index = build_index(clip)
    rnd = random.Random(1)
    with FrameDecoder(index) as dec:
        for _ in range(60):
            n = rnd.randrange(index.frame_count)
            assert number_of(dec.get(n), index) == n


def test_passed_frames_are_reported_in_order(h264_clip):
    index = build_index(h264_clip)
    seen = []
    with FrameDecoder(index) as dec:
        dec.get(45, on_passed=lambda i, f: seen.append((i, number_of(f, index))))
    assert [i for i, _ in seen] == list(range(30, 45))
    assert all(i == num for i, num in seen)


def test_rotation_applied(rotated_clip):
    index = build_index(rotated_clip)
    assert index.rotation == 90
    assert index.display_size == (240, 320)
    with FrameDecoder(index) as dec:
        rgb = to_rgb(dec.get(5), index)
    assert rgb.shape == (320, 240, 3)
    # Bottom-left red marker ends up bottom-right after a 90 degree ccw rotation.
    assert rgb[-5, -5, 0] > 200 and rgb[-5, -5, 2] < 60


def test_scaled_output(h264_clip):
    index = build_index(h264_clip)
    with FrameDecoder(index) as dec:
        rgb = to_rgb(dec.get(0), index, 160, 160)
    assert rgb.shape == (120, 160, 3)


def test_open_failure(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(VideoOpenError):
        build_index(bad)
