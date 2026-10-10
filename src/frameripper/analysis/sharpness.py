from __future__ import annotations

import numpy as np

ANALYSIS_WIDTH = 640
GRID_COLS = 8
TOP_FRACTION = 0.25
HIST_BINS = 32


def tile_sharpness(gray: np.ndarray, cols: int = GRID_COLS, top: float = TOP_FRACTION) -> float:
    """Mean Laplacian variance of the sharpest tiles.

    Scoring only the best tiles keeps a sharp subject on a soft background
    from being dragged down by the bokeh.
    """
    lap = laplacian(gray)
    h, w = lap.shape
    rows = max(1, round(cols * h / w))
    th, tw = h // rows, w // cols
    if th < 4 or tw < 4:
        return float(lap.var())
    tiles = lap[: th * rows, : tw * cols].reshape(rows, th, cols, tw)
    variances = tiles.var(axis=(1, 3)).ravel()
    k = max(1, round(len(variances) * top))
    return float(np.partition(variances, -k)[-k:].mean())


def laplacian(gray: np.ndarray) -> np.ndarray:
    """4-neighbour Laplacian of the interior pixels."""
    g = gray.astype(np.float32)
    return g[1:-1, :-2] + g[1:-1, 2:] + g[:-2, 1:-1] + g[2:, 1:-1] - 4 * g[1:-1, 1:-1]


def small(gray: np.ndarray, width: int = 160) -> np.ndarray:
    """Box-filter downscale by a whole factor, close to width."""
    f = max(1, gray.shape[1] // width)
    if f == 1:
        return gray.astype(np.float32)
    h, w = gray.shape[0] // f, gray.shape[1] // f
    return gray[: h * f, : w * f].reshape(h, f, w, f).mean(axis=(1, 3), dtype=np.float32)


def motion(prev_small: np.ndarray | None, cur_small: np.ndarray) -> float:
    if prev_small is None or prev_small.shape != cur_small.shape:
        return 0.0
    return float(np.abs(prev_small - cur_small).mean() / 255.0)


def histogram(gray_small: np.ndarray) -> np.ndarray:
    bins = (np.clip(gray_small, 0, 255).astype(np.uint16) * HIST_BINS) >> 8
    hist = np.bincount(bins.ravel(), minlength=HIST_BINS).astype(np.float32)
    return hist / max(hist.sum(), 1.0)


def hist_change(prev: np.ndarray | None, cur: np.ndarray) -> float:
    """Half L1 distance between histograms: 0 identical, 1 disjoint."""
    if prev is None:
        return 0.0
    return float(np.abs(prev - cur).sum() / 2.0)


def normalise(values: np.ndarray, pct: float = 98.0) -> np.ndarray:
    """Map raw sharpness to 0..1 relative to this video, NaN preserved.

    Laplacian variance grows with the square of edge contrast, so compare on
    the square root to keep the scale perceptually even.
    """
    out = np.full(values.shape, np.nan, dtype=np.float32)
    valid = ~np.isnan(values)
    if not valid.any():
        return out
    root = np.sqrt(np.maximum(values[valid], 0))
    ref = np.percentile(root, pct)
    if ref <= 0:
        out[valid] = 0
    else:
        out[valid] = np.clip(root / ref, 0, 1)
    return out


def local_peaks(scores: np.ndarray, radius: int, floor: float = 0.5) -> np.ndarray:
    """Frame numbers that are the maximum within +/-radius and at least floor."""
    if len(scores) == 0:
        return np.empty(0, dtype=np.int64)
    s = np.nan_to_num(scores, nan=-1.0)
    radius = max(1, radius)
    padded = np.pad(s, radius, mode="constant", constant_values=-1.0)
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * radius + 1)
    is_peak = (s >= windows.max(axis=1)) & (s >= floor)
    peaks = np.flatnonzero(is_peak)
    # Plateaus produce runs of equal peaks; keep the first of each run.
    if len(peaks) > 1:
        peaks = peaks[np.concatenate([[True], np.diff(peaks) > radius])]
    return peaks
