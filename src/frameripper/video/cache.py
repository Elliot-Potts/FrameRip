from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Hashable

import numpy as np


class FrameCache:
    """Thread-safe LRU of numpy frames bounded by total bytes."""

    def __init__(self, budget_bytes: int):
        self.budget = budget_bytes
        self._items: OrderedDict[Hashable, np.ndarray] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: Hashable) -> np.ndarray | None:
        with self._lock:
            arr = self._items.get(key)
            if arr is not None:
                self._items.move_to_end(key)
            return arr

    def __contains__(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._items

    def put(self, key: Hashable, arr: np.ndarray) -> None:
        with self._lock:
            old = self._items.pop(key, None)
            if old is not None:
                self._bytes -= old.nbytes
            if arr.nbytes > self.budget:
                return
            self._items[key] = arr
            self._bytes += arr.nbytes
            while self._bytes > self.budget:
                _, evicted = self._items.popitem(last=False)
                self._bytes -= evicted.nbytes

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._bytes = 0

    @property
    def nbytes(self) -> int:
        return self._bytes

    def __len__(self) -> int:
        return len(self._items)
