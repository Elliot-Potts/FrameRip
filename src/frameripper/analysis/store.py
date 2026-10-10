from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from frameripper.analysis.data import Analysis

ANALYSIS_VERSION = 1


def video_key(video_path: str | Path) -> str:
    p = Path(video_path).resolve()
    st = p.stat()
    raw = f"{str(p).lower() if os.name == 'nt' else p}|{st.st_size}|{st.st_mtime_ns}"
    return hashlib.sha1(raw.encode()).hexdigest()[:20]


class Store:
    """Per-video analysis results and session state, kept in the app data dir."""

    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _path(self, key: str, suffix: str) -> Path:
        return self.root / f"{key}{suffix}"

    def load_analysis(self, key: str, frame_count: int) -> Analysis | None:
        path = self._path(key, ".analysis.npz")
        try:
            with np.load(path) as data:
                if int(data["version"]) != ANALYSIS_VERSION:
                    return None
                a = Analysis(
                    sharpness=data["sharpness"].astype(np.float32),
                    motion=data["motion"].astype(np.float32),
                    change=data["change"].astype(np.float32),
                    complete=True,
                )
        except (OSError, KeyError, ValueError):
            return None
        if a.frame_count != frame_count:
            return None
        return a

    def save_analysis(self, key: str, analysis: Analysis) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._path(key, ".analysis.npz")
        tmp = path.with_suffix(".tmp.npz")
        np.savez_compressed(
            tmp,
            version=ANALYSIS_VERSION,
            sharpness=analysis.sharpness,
            motion=analysis.motion,
            change=analysis.change,
        )
        os.replace(tmp, path)

    def load_session(self, key: str) -> dict:
        try:
            return json.loads(self._path(key, ".session.json").read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def save_session(self, key: str, session: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._path(key, ".session.json").write_text(json.dumps(session), "utf-8")
