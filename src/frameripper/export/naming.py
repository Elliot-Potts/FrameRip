from __future__ import annotations

import re
import string
from pathlib import Path

DEFAULT_TEMPLATE = "{name}_{time}_f{frame}"
TOKENS = {
    "name": "video file name",
    "frame": "frame number",
    "time": "timecode HH-MM-SS-mmm",
    "score": "sharpness 0-100",
    "n": "position in batch",
}

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def timecode(seconds: float, sep: str = "-") -> str:
    ms_total = int(round(max(seconds, 0.0) * 1000))
    h, rem = divmod(ms_total, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}{sep}{m:02d}{sep}{s:02d}{sep}{ms:03d}"


def display_timecode(seconds: float) -> str:
    t = timecode(seconds, ":")
    return t[:8] + "." + t[9:]


class _Values(dict):
    def __missing__(self, key):
        return _Literal(key)


class _Literal:
    """Unknown tokens are left in the name as written."""

    def __init__(self, key: str):
        self.key = key

    def __format__(self, spec: str) -> str:
        return "{" + self.key + (":" + spec if spec else "") + "}"


def expand(
    template: str,
    *,
    name: str,
    frame: int,
    seconds: float,
    score: float | None = None,
    n: int = 1,
) -> str:
    values = _Values(
        name=name,
        frame=frame,
        time=timecode(seconds),
        score=int(round(score)) if score is not None else "na",
        n=n,
    )
    try:
        out = string.Formatter().vformat(template, (), values)
    except (ValueError, IndexError, TypeError, AttributeError):
        out = template
    out = _INVALID.sub("_", out).strip(" .")
    return out or f"{name}_f{frame}"


def unique_path(folder: Path, stem: str, ext: str) -> Path:
    path = folder / f"{stem}.{ext}"
    i = 1
    while path.exists():
        path = folder / f"{stem}_{i}.{ext}"
        i += 1
    return path
