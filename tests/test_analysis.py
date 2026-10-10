import numpy as np
import pytest
from PIL import Image, ImageFilter

from frameripper.analysis import autopick
from frameripper.analysis.data import Analysis
from frameripper.analysis.sharpness import (
    hist_change,
    histogram,
    local_peaks,
    motion,
    normalise,
    small,
    tile_sharpness,
)
from frameripper.analysis.store import Store, video_key


@pytest.fixture
def texture():
    rng = np.random.default_rng(3)
    img = (rng.random((90, 160)) * 255).astype(np.uint8)
    return np.asarray(Image.fromarray(img).resize((640, 360), Image.NEAREST))


def blur(img: np.ndarray, sigma: float) -> np.ndarray:
    return np.asarray(Image.fromarray(img).filter(ImageFilter.GaussianBlur(sigma)))


def test_blur_lowers_score(texture):
    scores = [tile_sharpness(blur(texture, s)) for s in (0.1, 1, 2, 4)]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] > 2 * scores[-1]


def test_shallow_focus_beats_uniform_blur(texture):
    uniform = blur(texture, 3)
    shallow = uniform.copy()
    shallow[120:240, 240:400] = texture[120:240, 240:400]
    assert tile_sharpness(shallow) > 2 * tile_sharpness(uniform)


def test_small_motion_and_histogram(texture):
    a = small(texture)
    assert a.shape == (90, 160)
    assert motion(None, a) == 0.0
    assert motion(a, a) == 0.0
    assert motion(a, 255 - a) > 0.2
    h = histogram(a)
    assert h.shape == (32,) and h.sum() == pytest.approx(1.0)
    assert hist_change(h, h) == 0.0
    assert hist_change(histogram(np.zeros((10, 10))), histogram(np.full((10, 10), 255))) == 1.0


def test_normalise_keeps_nan():
    v = np.array([0, 1, 4, np.nan, 100], dtype=np.float32)
    out = normalise(v)
    assert np.isnan(out[3])
    assert out[4] == pytest.approx(1.0)
    assert 0 <= out[0] < out[1] < out[2] < 1


def test_local_peaks():
    s = np.array([0.1, 0.9, 0.2, 0.2, 0.3, 0.8, 0.1, 0.1, 0.4], dtype=np.float32)
    assert local_peaks(s, radius=2).tolist() == [1, 5]


def test_cuts_and_scenes():
    change = np.zeros(100, dtype=np.float32)
    change[30] = 0.9
    change[31] = 0.5
    change[70] = 0.6
    assert autopick.detect_cuts(change) == [30, 70]
    assert autopick.scenes(change) == [(0, 30), (30, 70), (70, 100)]


def test_pick_per_scene_avoids_motion_and_cuts():
    n = 90
    sharp = np.full(n, 10.0, dtype=np.float32)
    motion = np.zeros(n, dtype=np.float32)
    change = np.zeros(n, dtype=np.float32)
    change[45] = 0.8
    sharp[20] = 50  # sharp and still
    sharp[10] = 60
    motion[10] = 1.0  # sharper but moving a lot
    sharp[45] = 100  # sits on the cut itself
    sharp[60] = 40
    picks = autopick.pick_per_scene(sharp, motion, change)
    assert picks == [20, 60]


def test_pick_per_window():
    times = np.arange(90) / 30.0
    sharp = np.ones(90, dtype=np.float32)
    sharp[[5, 40, 85]] = 10
    zero = np.zeros(90, dtype=np.float32)
    assert autopick.pick_per_window(sharp, zero, zero, times, 1.0) == [5, 40, 85]


def test_pick_skips_unanalysed():
    times = np.arange(60) / 30.0
    sharp = np.full(60, np.nan, dtype=np.float32)
    sharp[:30] = 1
    sharp[12] = 5
    zero = np.zeros(60, dtype=np.float32)
    assert autopick.pick_per_window(sharp, zero, zero, times, 1.0) == [12]


def test_store_roundtrip(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    key = video_key(video)
    store = Store(tmp_path / "store")
    a = Analysis.empty(5)
    a.sharpness[:] = [1, 2, 3, 4, 5]
    a.motion[:] = 0
    a.change[:] = 0
    store.save_analysis(key, a)
    loaded = store.load_analysis(key, 5)
    assert loaded is not None and loaded.complete
    assert loaded.sharpness.tolist() == [1, 2, 3, 4, 5]
    assert store.load_analysis(key, 6) is None

    store.save_session(key, {"marked": [1]})
    assert store.load_session(key) == {"marked": [1]}

    video.write_bytes(b"changed")
    assert video_key(video) != key
