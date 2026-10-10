"""Synthetic test clips whose frames carry their own frame number."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path

import av
import numpy as np

BITS = 12
BLOCK = 16


def make_frame(n: int, w: int, h: int) -> np.ndarray:
    img = np.full((h, w, 3), 90, np.uint8)
    # Mark the top-left corner so orientation can be checked after rotation.
    img[h - 24 :, :24] = (255, 0, 0)
    for bit in range(BITS):
        if (n >> bit) & 1:
            img[0:BLOCK, bit * BLOCK : (bit + 1) * BLOCK] = 255
        else:
            img[0:BLOCK, bit * BLOCK : (bit + 1) * BLOCK] = 0
    return img


def read_number(img: np.ndarray) -> int:
    n = 0
    for bit in range(BITS):
        y, x = BLOCK // 2, bit * BLOCK + BLOCK // 2
        if img[y, x].mean() > 128:
            n |= 1 << bit
    return n


def write_clip(
    path: Path,
    count: int,
    *,
    codec: str = "libx264",
    size: tuple[int, int] = (320, 240),
    gop: int = 30,
    rotation: int = 0,
    vfr: bool = False,
) -> Path:
    w, h = size
    with av.open(str(path), "w") as c:
        if vfr:
            s = c.add_stream(codec, rate=1000)
            s.codec_context.time_base = Fraction(1, 1000)
        else:
            s = c.add_stream(codec, rate=30)
        s.width, s.height = w, h
        s.pix_fmt = "yuv420p"
        s.codec_context.gop_size = gop
        if codec in ("libx264", "libx265"):
            s.options = {"crf": "12", "preset": "veryfast"}
        if rotation:
            s.set_display_rotation(rotation)
        t = 0
        rng = np.random.default_rng(0)
        for i in range(count):
            f = av.VideoFrame.from_ndarray(make_frame(i, w, h), format="rgb24")
            if vfr:
                f.pts = t
                f.time_base = Fraction(1, 1000)
                t += int(rng.choice([16, 17, 33, 50]))
            for p in s.encode(f):
                c.mux(p)
        for p in s.encode():
            c.mux(p)
    return path
