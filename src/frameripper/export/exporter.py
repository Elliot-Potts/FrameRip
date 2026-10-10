from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin

from frameripper.export import naming
from frameripper.video.decoder import FrameDecoder, to_rgb
from frameripper.video.index import FrameIndex

FORMATS = {
    "png": "PNG",
    "jpg": "JPEG",
    "webp": "WebP",
    "tiff": "TIFF",
}
LOSSY = {"jpg", "webp"}


@dataclass
class ExportOptions:
    folder: Path
    fmt: str = "png"
    quality: int = 95
    template: str = naming.DEFAULT_TEMPLATE


@dataclass
class ExportItem:
    frame: int
    score: float | None = None
    n: int = 1


@dataclass
class ExportResult:
    paths: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def save_image(rgb: np.ndarray, path: Path, fmt: str, quality: int, info: dict | None = None):
    img = Image.fromarray(rgb, "RGB")
    kwargs: dict = {}
    if fmt == "png":
        kwargs["compress_level"] = 4
        if info:
            meta = PngImagePlugin.PngInfo()
            for k, v in info.items():
                meta.add_text(k, str(v))
            kwargs["pnginfo"] = meta
    elif fmt == "jpg":
        kwargs.update(quality=quality, subsampling=0 if quality >= 90 else 2, optimize=True)
    elif fmt == "webp":
        kwargs.update(quality=quality, lossless=quality >= 100, method=4)
    elif fmt == "tiff":
        kwargs["compression"] = "tiff_lzw"
    img.save(path, FORMATS[fmt], **kwargs)


def target_path(index: FrameIndex, item: ExportItem, opts: ExportOptions) -> Path:
    stem = naming.expand(
        opts.template,
        name=index.name,
        frame=item.frame,
        seconds=index.time_of(item.frame),
        score=item.score,
        n=item.n,
    )
    return naming.unique_path(opts.folder, stem, opts.fmt)


def decode_full(decoder: FrameDecoder, n: int) -> np.ndarray:
    return to_rgb(decoder.get(n), decoder.index, quality=True)


def export_frames(
    index: FrameIndex,
    items: list[ExportItem],
    opts: ExportOptions,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ExportResult:
    result = ExportResult()
    opts.folder.mkdir(parents=True, exist_ok=True)
    # Ascending order lets the decoder run forward instead of seeking each time.
    ordered = sorted(items, key=lambda it: it.frame)
    with FrameDecoder(index) as dec:
        for i, item in enumerate(ordered):
            if cancelled is not None and cancelled():
                break
            try:
                rgb = decode_full(dec, item.frame)
                path = target_path(index, item, opts)
                info = {
                    "Source": Path(index.path).name,
                    "Frame": item.frame,
                    "Timecode": naming.display_timecode(index.time_of(item.frame)),
                }
                save_image(rgb, path, opts.fmt, opts.quality, info)
                result.paths.append(path)
            except Exception as e:  # keep going so one bad frame doesn't sink a batch
                result.errors.append(f"frame {item.frame}: {e}")
            if progress is not None:
                progress(i + 1, len(ordered))
    return result
