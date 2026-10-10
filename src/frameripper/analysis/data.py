from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from frameripper.analysis.sharpness import local_peaks, normalise


@dataclass
class Analysis:
    """Per-frame measurements. NaN marks frames not analysed yet."""

    sharpness: np.ndarray
    motion: np.ndarray
    change: np.ndarray
    complete: bool = False
    version: int = 0  # bumped whenever values change, for cheap cache invalidation
    _norm: np.ndarray | None = field(default=None, repr=False)
    _norm_version: int = field(default=-1, repr=False)

    @classmethod
    def empty(cls, count: int) -> Analysis:
        def nan():
            return np.full(count, np.nan, dtype=np.float32)

        return cls(sharpness=nan(), motion=nan(), change=nan())

    @property
    def frame_count(self) -> int:
        return len(self.sharpness)

    @property
    def analysed(self) -> int:
        return int(np.count_nonzero(~np.isnan(self.sharpness)))

    def normalised(self) -> np.ndarray:
        if self._norm_version != self.version or self._norm is None:
            self._norm = normalise(self.sharpness)
            self._norm_version = self.version
        return self._norm

    def score(self, n: int) -> float | None:
        """0-100 sharpness relative to the rest of this video."""
        v = self.normalised()[n]
        return None if np.isnan(v) else float(v * 100)

    def peaks(self, radius: int) -> np.ndarray:
        return local_peaks(self.normalised(), radius)
