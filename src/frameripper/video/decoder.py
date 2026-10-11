from __future__ import annotations

from collections.abc import Callable, Iterator

import av
import numpy as np
from av.video.reformatter import ColorRange, Colorspace, Interpolation

from frameripper.video.index import FrameIndex

_UNSPECIFIED_COLORSPACE = 2

PassedCallback = Callable[[int, av.VideoFrame], None]


class DecodeAborted(Exception):
    pass


class FrameDecoder:
    """Exact frame access on top of a FrameIndex.

    Not thread-safe: each thread that decodes should own its own instance.
    """

    def __init__(self, index: FrameIndex):
        self.index = index
        self._container = av.open(index.path)
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"
        self._frames: Iterator[av.VideoFrame] | None = None
        self._pos = -1  # frame number of the last frame pulled from _frames
        self._pending: av.VideoFrame | None = None
        self._last: tuple[int, av.VideoFrame] | None = None

    def close(self) -> None:
        self._frames = None
        self._container.close()

    def __enter__(self) -> FrameDecoder:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def position(self) -> int:
        return self._pos

    def get(
        self,
        n: int,
        on_passed: PassedCallback | None = None,
        should_abort: Callable[[], bool] | None = None,
    ) -> av.VideoFrame:
        """Decode frame n. Frames decoded on the way are handed to on_passed."""
        idx = self.index
        n = idx.clamp(n)
        if self._last is not None and self._last[0] == n:
            return self._last[1]

        # Decoding forward is cheaper than seeking unless a keyframe lies between us and n.
        can_continue = (
            self._frames is not None and self._pos < n and idx.keyframe_before(n) <= self._pos
        )
        if not can_continue:
            self._seek(n)

        while True:
            frame = self._next()
            if frame is None:
                # Ran off the end; the index promised more frames than exist.
                self._frames = None
                raise EOFError(f"frame {n} could not be decoded")
            if self._pos >= n:
                self._last = (n, frame)
                return frame
            if on_passed is not None:
                on_passed(self._pos, frame)
            if should_abort is not None and should_abort():
                raise DecodeAborted()

    def _seek(self, n: int) -> None:
        idx = self.index
        self._pending = None
        key = idx.keyframe_before(n)
        # Some demuxers land past the requested keyframe, so back off until the
        # first decoded frame is at or before the target.
        for attempt in range(4):
            target = idx.keyframes[max(0, int(np.searchsorted(idx.keyframes, key)) - attempt)]
            self._container.seek(int(idx.pts[target]), backward=True, stream=self._stream)
            self._frames = self._container.decode(self._stream)
            self._pos = -1
            first = self._next()
            if first is not None and self._pos <= n:
                self._pending = first
                return
        self._container.seek(int(idx.pts[0]), backward=True, stream=self._stream)
        self._frames = self._container.decode(self._stream)
        self._pos = -1

    def _next(self) -> av.VideoFrame | None:
        if self._pending is not None:
            frame, self._pending = self._pending, None
            return frame
        assert self._frames is not None
        try:
            frame = next(self._frames)
        except StopIteration:
            return None
        except av.error.FFmpegError:
            # Corrupt packet; skip it rather than giving up on the whole stream.
            return self._next_after_error()
        self._advance(frame)
        return frame

    def _next_after_error(self) -> av.VideoFrame | None:
        for _ in range(8):
            try:
                frame = next(self._frames)
            except StopIteration:
                return None
            except av.error.FFmpegError:
                continue
            self._advance(frame)
            return frame
        return None

    def _advance(self, frame: av.VideoFrame) -> None:
        if frame.pts is None:
            self._pos += 1
        else:
            self._pos = self.index.frame_of_pts(frame.pts)


def scaled_size(index: FrameIndex, max_w: int | None, max_h: int | None) -> tuple[int, int]:
    """Output size in display orientation, fitted inside max_w x max_h."""
    w, h = index.display_size
    if max_w and max_h and (w > max_w or h > max_h):
        s = min(max_w / w, max_h / h)
        w, h = max(2, round(w * s)), max(2, round(h * s))
    return w, h


def to_rgb(
    frame: av.VideoFrame,
    index: FrameIndex,
    max_w: int | None = None,
    max_h: int | None = None,
    quality: bool = False,
) -> np.ndarray:
    """Convert a decoded frame to an HxWx3 uint8 RGB array in display orientation."""
    out_w, out_h = scaled_size(index, max_w, max_h)
    if index.rotation % 180 != 0:
        out_w, out_h = out_h, out_w

    colorspace = None
    if frame.colorspace == _UNSPECIFIED_COLORSPACE:
        # Match what players assume for untagged video.
        colorspace = Colorspace.ITU709 if frame.height >= 720 else Colorspace.ITU601

    src_range = frame.color_range if frame.color_range != ColorRange.UNSPECIFIED else None
    interp = Interpolation.BICUBIC | Interpolation.ACCURATE_RND if quality else Interpolation.AREA
    if out_w == frame.width and out_h == frame.height:
        interp = Interpolation.POINT | Interpolation.ACCURATE_RND | Interpolation.FULL_CHR_H_INT

    rgb = frame.reformat(
        width=out_w,
        height=out_h,
        format="rgb24",
        src_colorspace=colorspace,
        dst_colorspace=colorspace,
        src_color_range=src_range,
        dst_color_range=ColorRange.JPEG,
        interpolation=interp,
    ).to_ndarray()

    if index.rotation:
        rgb = np.rot90(rgb, k=index.rotation // 90)
    # FFmpeg pads rows to 16 bytes, so narrow outputs come back as strided views.
    # Qt and the caches need tightly packed rows.
    return np.ascontiguousarray(rgb)


def to_gray(frame: av.VideoFrame, width: int) -> np.ndarray:
    """Downscaled luma for analysis; orientation does not matter here."""
    height = max(2, round(frame.height * width / frame.width))
    return frame.reformat(
        width=width, height=height, format="gray", interpolation=Interpolation.AREA
    ).to_ndarray()
