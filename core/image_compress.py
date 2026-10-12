"""Batch image compression with resizing. Originals are never touched unless overwrite mode is chosen."""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

from PIL import Image, ImageOps, UnidentifiedImageError

from .common import (InvalidInputError, JobContext, Result, check_output_dir, friendly_os_error, human_size,
                     size_change, unique_path)

SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
_FMT_FOR_EXT = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".webp": "WEBP", ".bmp": "BMP",
                ".tif": "TIFF", ".tiff": "TIFF"}
_EXT_FOR_FMT = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "TIFF": ".tif"}


@dataclass
class ImageInfo:
    path: Path
    width: int
    height: int
    format: str
    size: int
    has_alpha: bool


@dataclass
class ImageOutcome:
    source: Path
    output: Optional[Path]
    original_size: int
    new_size: int
    original_dims: tuple[int, int]
    new_dims: tuple[int, int]
    skipped: bool = False
    note: str = ""

    @property
    def percent_saved(self) -> float:
        return (self.original_size - self.new_size) / self.original_size * 100 if self.original_size else 0.0


@dataclass
class CompressOptions:
    quality: int = 80                   # JPEG / WebP quality 1-100
    max_width: Optional[int] = None
    max_height: Optional[int] = None
    out_format: str = "same"            # "same" | "jpeg" | "png" | "webp"
    png_reduce_colors: bool = False     # lossy 256-colour palette: good for graphics, bad for photos
    suffix: str = "_compressed"
    overwrite_originals: bool = False   # replace source files (only when the result is smaller)


def image_info(path: Path) -> ImageInfo:
    path = Path(path)
    try:
        with Image.open(path) as im:
            alpha = im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
            return ImageInfo(path, im.width, im.height, im.format or "?", path.stat().st_size, alpha)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidInputError(f"'{path.name}' is not a readable image.") from exc


def _flatten(im: Image.Image) -> Image.Image:
    """Put transparency on white (needed when saving to JPEG)."""
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        rgba = im.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.getchannel("A"))
        return bg
    return im.convert("RGB") if im.mode != "RGB" else im


def _target_format(src_fmt: str, ext: str, opt: CompressOptions) -> tuple[str, str]:
    if opt.out_format != "same":
        fmt = opt.out_format.upper()
        return fmt, _EXT_FOR_FMT[fmt]
    if src_fmt == "BMP":  # uncompressed format: PNG is lossless and normally far smaller
        return "PNG", ".png"
    return src_fmt, ext if src_fmt != "JPEG" else ".jpg" if ext == ".jpg" else ".jpeg"


def _load(src: Path) -> tuple[Image.Image, str, object, int]:
    """Decode fully and close the file handle, so the source can be replaced afterwards (Windows)."""
    with Image.open(src) as im:
        src_fmt = im.format or _FMT_FOR_EXT[src.suffix.lower()]
        frames = getattr(im, "n_frames", 1)
        im.load()
        icc = im.info.get("icc_profile")
        work = ImageOps.exif_transpose(im)  # bakes orientation in; other EXIF (e.g. GPS) is dropped
        if work is None or work is im:
            work = im.copy()
    return work, src_fmt, icc, frames


def _compress_one(src: Path, out_dir: Optional[Path], opt: CompressOptions) -> ImageOutcome:
    ext = src.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise InvalidInputError(f"'{src.name}' is not a supported image type.")
    info = image_info(src)
    orig_dims = (info.width, info.height)
    notes: list[str] = []
    work, src_fmt, icc, frames = _load(src)
    if frames > 1 and src_fmt in ("TIFF", "WEBP"):
        notes.append("multi-frame image: only the first frame was kept")
    fmt, new_ext = _target_format(src_fmt, ext, opt)
    resized = False
    if opt.max_width or opt.max_height:
        box = (opt.max_width or work.width, opt.max_height or work.height)
        if work.width > box[0] or work.height > box[1]:  # never upscale
            work.thumbnail(box, Image.Resampling.LANCZOS)
            resized = True
    fmt_changed = fmt != src_fmt
    overwrite = opt.overwrite_originals
    if overwrite:
        same_ext = new_ext == ext or (fmt == "JPEG" and ext in (".jpg", ".jpeg"))
        target = src if same_ext else unique_path(src.with_suffix(new_ext))
    else:
        target = unique_path((out_dir or src.parent) / f"{src.stem}{opt.suffix}{new_ext}")
    tmp = target.with_name(f".{target.stem[:50]}.{uuid.uuid4().hex[:8]}.tmp{target.suffix}")
    try:
        kw: dict = {}
        if fmt == "JPEG":
            work = _flatten(work) if work.mode not in ("RGB", "L") else work
            kw = dict(quality=opt.quality, optimize=True, progressive=True)
            if icc:
                kw["icc_profile"] = icc
        elif fmt == "WEBP":
            if work.mode not in ("RGB", "RGBA", "L"):
                work = work.convert("RGBA" if "A" in work.getbands() or "transparency" in work.info else "RGB")
            kw = dict(quality=opt.quality, method=6)
            if icc:
                kw["icc_profile"] = icc
        elif fmt == "PNG":
            if opt.png_reduce_colors and work.mode in ("RGB", "RGBA"):
                work = work.quantize(256, method=Image.Quantize.FASTOCTREE if work.mode == "RGBA"
                                     else Image.Quantize.MEDIANCUT)
            kw = dict(optimize=True, compress_level=9)
        elif fmt == "TIFF":
            kw = dict(compression="tiff_adobe_deflate")
        work.save(tmp, fmt, **kw)
        new_size = tmp.stat().st_size
        if (not fmt_changed and not resized and new_size >= info.size) or (overwrite and new_size >= info.size):
            tmp.unlink(missing_ok=True)  # recompression would not help - leave everything as it is
            note = "already well compressed; no smaller version possible" if not overwrite else \
                "result was not smaller; original kept"
            return ImageOutcome(src, None, info.size, info.size, orig_dims, orig_dims, True, note)
        with Image.open(tmp) as check:  # verify the output really decodes
            check.load()
            new_dims = check.size
        os.replace(tmp, target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise friendly_os_error(exc, target) from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if fmt_changed and src_fmt == "BMP" and opt.out_format == "same":
        notes.append("BMP saved as PNG (lossless)")
    return ImageOutcome(src, target, info.size, new_size, orig_dims, new_dims, False, "; ".join(notes))


def compress_images(inputs: Sequence[Path], output_dir: Optional[Path], options: CompressOptions | None = None, *,
                    ctx: JobContext | None = None) -> Result:
    """Batch-compress. A failure on one file does not stop the others; it is reported in ``warnings``."""
    ctx = ctx or JobContext()
    opt = options or CompressOptions()
    inputs = [Path(p) for p in inputs]
    if not inputs:
        raise InvalidInputError("Add at least one image.")
    if not 1 <= opt.quality <= 100:
        raise InvalidInputError("Quality must be between 1 and 100.")
    if not opt.overwrite_originals:
        out_dir = check_output_dir(output_dir) if output_dir else None
    else:
        out_dir = None
    outcomes: list[ImageOutcome] = []
    warnings: list[str] = []
    for i, p in enumerate(inputs):
        ctx.step(i, len(inputs), f"Compressing {p.name}")
        try:
            outcomes.append(_compress_one(p, out_dir, opt))
        except InvalidInputError as exc:
            warnings.append(str(exc))
        except OSError as exc:
            warnings.append(f"{p.name}: {exc}")
        except Image.DecompressionBombError:
            warnings.append(f"'{p.name}' is too large to process safely.")
    if not outcomes:
        raise InvalidInputError("None of the selected images could be processed. " + " ".join(warnings))
    done = [o for o in outcomes if not o.skipped]
    before = sum(o.original_size for o in outcomes)
    after = sum(o.new_size for o in outcomes)
    for o in outcomes:
        if o.skipped:
            warnings.append(f"{o.source.name}: {o.note}.")
    msg = f"Processed {len(outcomes)} image(s), {len(done)} written. Total: {size_change(before, after)}."
    return Result([o.output for o in done if o.output], msg, warnings,
                  {"outcomes": outcomes, "before": before, "after": after})
