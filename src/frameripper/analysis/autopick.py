from __future__ import annotations

import numpy as np

from frameripper.analysis.sharpness import FEATURELESS, normalise

MOTION_PENALTY = 0.35
MOTION_FULL_SCALE = 0.08
CUT_GUARD = 2  # frames either side of a cut that are likely blended
MIN_QUALITY = 0.05  # scenes whose best frame is among the very softest get no pick


def quality(sharpness: np.ndarray, motion: np.ndarray) -> np.ndarray:
    sharp = normalise(sharpness)
    # Motion is mean abs frame difference; around 0.08 is already a fast pan.
    mot_n = np.clip(np.nan_to_num(motion, nan=0.0) / MOTION_FULL_SCALE, 0, 1)
    q = np.nan_to_num(sharp, nan=-1.0) - MOTION_PENALTY * mot_n
    q[np.nan_to_num(sharpness, nan=0.0) < FEATURELESS] = -1.0
    return q


def detect_cuts(change: np.ndarray, threshold: float = 0.35, min_gap: int = 8) -> list[int]:
    """Frame numbers that start a new scene."""
    c = np.nan_to_num(change, nan=0.0)
    cuts: list[int] = []
    for n in np.flatnonzero(c > threshold):
        n = int(n)
        if cuts and n - cuts[-1] < min_gap:
            if c[n] > c[cuts[-1]]:
                cuts[-1] = n
            continue
        cuts.append(n)
    return cuts


def scenes(change: np.ndarray, threshold: float = 0.35) -> list[tuple[int, int]]:
    """Half-open (start, end) ranges between cuts."""
    total = len(change)
    bounds = [0, *[c for c in detect_cuts(change, threshold) if c > 0], total]
    return [(a, b) for a, b in zip(bounds, bounds[1:], strict=False) if b > a]


def _best_in(q: np.ndarray, start: int, end: int, guarded: np.ndarray) -> int | None:
    if end <= start:
        return None
    seg = q[start:end].copy()
    seg[guarded[start:end]] = -np.inf
    if not np.isfinite(seg).any():
        seg = q[start:end]
    best = int(np.argmax(seg))
    if seg[best] < MIN_QUALITY:
        return None
    return start + best


def _guard_mask(total: int, cuts: list[int]) -> np.ndarray:
    mask = np.zeros(total, dtype=bool)
    for c in cuts:
        mask[max(0, c - CUT_GUARD) : min(total, c + CUT_GUARD + 1)] = True
    return mask


def pick_per_window(
    sharpness: np.ndarray, motion: np.ndarray, change: np.ndarray, times: np.ndarray, window: float
) -> list[int]:
    q = quality(sharpness, motion)
    guarded = _guard_mask(len(q), detect_cuts(change))
    picks = []
    edges = np.arange(0.0, float(times[-1]) + window, window)
    bounds = np.searchsorted(times, edges, side="left")
    for a, b in zip(bounds, bounds[1:], strict=False):
        best = _best_in(q, int(a), int(b), guarded)
        if best is not None:
            picks.append(best)
    return picks


def pick_per_scene(sharpness: np.ndarray, motion: np.ndarray, change: np.ndarray) -> list[int]:
    q = quality(sharpness, motion)
    cuts = detect_cuts(change)
    guarded = _guard_mask(len(q), cuts)
    picks = []
    for a, b in scenes(change):
        best = _best_in(q, a, b, guarded)
        if best is not None:
            picks.append(best)
    return picks
