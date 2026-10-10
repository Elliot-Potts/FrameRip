from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np


class VideoOpenError(Exception):
    pass


@dataclass(frozen=True, eq=False)
class FrameIndex:
    """Exact per-frame timestamps for the first video stream of a file.

    Frame numbers are positions in display order. Everything else in the app
    addresses frames by number and derives time from here.
    """

    path: str
    pts: np.ndarray  # int64, sorted display order
    keyframes: np.ndarray  # frame numbers of keyframes, sorted
    time_base: Fraction
    width: int
    height: int
    rotation: int  # degrees counter-clockwise needed for display
    sar: Fraction
    avg_fps: float
    codec: str

    @property
    def frame_count(self) -> int:
        return len(self.pts)

    @property
    def name(self) -> str:
        return Path(self.path).stem

    @property
    def duration(self) -> float:
        if self.frame_count == 0:
            return 0.0
        return self.time_of(self.frame_count - 1) + 1.0 / self.avg_fps

    @property
    def display_size(self) -> tuple[int, int]:
        """Size after applying sample aspect ratio and rotation."""
        w = round(self.width * self.sar) if self.sar != 1 else self.width
        h = self.height
        if self.rotation % 180 != 0:
            w, h = h, w
        return w, h

    def time_of(self, n: int) -> float:
        return float((int(self.pts[n]) - int(self.pts[0])) * self.time_base)

    def frame_at_time(self, seconds: float) -> int:
        target = int(self.pts[0]) + seconds / self.time_base
        n = int(np.searchsorted(self.pts, target, side="right")) - 1
        return self.clamp(n)

    def frame_of_pts(self, pts: int) -> int:
        n = int(np.searchsorted(self.pts, pts, side="left"))
        if n >= self.frame_count:
            return self.frame_count - 1
        if self.pts[n] != pts and n > 0 and pts - self.pts[n - 1] < self.pts[n] - pts:
            n -= 1
        return n

    def keyframe_before(self, n: int) -> int:
        i = int(np.searchsorted(self.keyframes, n, side="right")) - 1
        return int(self.keyframes[max(i, 0)])

    def clamp(self, n: int) -> int:
        return max(0, min(int(n), self.frame_count - 1))


def _first_frame(container: av.container.InputContainer, stream) -> av.VideoFrame | None:
    for frame in container.decode(stream):
        return frame
    return None


def build_index(path: str | Path) -> FrameIndex:
    path = str(Path(path).resolve())
    try:
        container = av.open(path)
    except (av.error.FFmpegError, OSError) as e:
        raise VideoOpenError(f"Could not open {Path(path).name}: {e}") from e

    with container:
        if not container.streams.video:
            raise VideoOpenError(f"{Path(path).name} has no video stream")
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"

        try:
            first = _first_frame(container, stream)
        except av.error.FFmpegError as e:
            raise VideoOpenError(f"Could not decode {Path(path).name}: {e}") from e
        if first is None:
            raise VideoOpenError(f"{Path(path).name} contains no decodable frames")

        container.seek(0, backward=True, stream=stream)
        stamps: list[int] = []
        key_stamps: list[int] = []
        last = None
        for packet in container.demux(stream):
            if packet.size == 0 or packet.is_discard:
                continue
            ts = packet.pts if packet.pts is not None else packet.dts
            if ts is None:
                # No timestamps at all (raw elementary streams); synthesise them.
                ts = 0 if last is None else last + 1
            last = ts
            stamps.append(ts)
            if packet.is_keyframe:
                key_stamps.append(ts)

        time_base = stream.time_base or Fraction(1, 1000)
        average_rate = stream.average_rate
        sar = stream.sample_aspect_ratio
        codec = stream.codec_context.name

    pts = np.unique(np.asarray(stamps, dtype=np.int64))
    if len(pts) == 0:
        raise VideoOpenError(f"{Path(path).name} contains no video packets")

    # Decoders can drop leading frames (edit lists, open GOP), so start where
    # decoding actually starts.
    if first.pts is not None and first.pts > pts[0]:
        pts = pts[pts >= first.pts]

    keys = np.searchsorted(pts, np.asarray(key_stamps, dtype=np.int64))
    keys = np.unique(np.clip(keys, 0, len(pts) - 1))
    if len(keys) == 0 or keys[0] != 0:
        keys = np.concatenate([[0], keys])

    if len(pts) > 1:
        span = float((pts[-1] - pts[0]) * time_base)
        avg_fps = (len(pts) - 1) / span if span > 0 else 30.0
    else:
        avg_fps = float(average_rate or 30)

    sar = Fraction(sar) if sar and sar > 0 else Fraction(1)

    return FrameIndex(
        path=path,
        pts=pts,
        keyframes=keys.astype(np.int64),
        time_base=Fraction(time_base),
        width=first.width,
        height=first.height,
        rotation=int(round((first.rotation or 0) / 90.0)) * 90 % 360,
        sar=sar,
        avg_fps=avg_fps,
        codec=codec,
    )
