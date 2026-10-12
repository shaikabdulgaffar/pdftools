"""Image to PDF - JPG, PNG, BMP, TIFF and WebP images into one PDF."""
from __future__ import annotations

import io
import pymupdf
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from utils import (
    InvalidInputError, JobContext, Option, Request, Result, ToolDef, atomic_output, save_pdf, stem,
    validate_output_pdf,
)


SUPPORTED_EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp")
PAGE_SIZES = {"a4": (595.0, 842.0), "letter": (612.0, 792.0)}  # points, portrait
MM = 72 / 25.4


@dataclass
class LayoutOptions:
    page_size: str = "a4"          # "a4" | "letter" | "image" (page = image size + margins)
    orientation: str = "auto"      # "auto" | "portrait" | "landscape"
    margin_mm: float = 10.0
    placement: str = "fit"         # "fit" (scale to margins) | "actual" (real size, shrink only if too big)
    alignment: str = "center"      # "center" | "top"


def _normalise(img: Image.Image) -> Image.Image:
    """Convert exotic modes to something PDF/PNG can store without losing transparency."""
    if img.mode in ("RGB", "L", "RGBA"):
        return img
    if img.mode == "P":
        return img.convert("RGBA" if "transparency" in img.info else "RGB")
    if img.mode in ("LA", "PA"):
        return img.convert("RGBA")
    if img.mode in ("I;16", "I", "F"):
        return img.convert("I").point(lambda v: v * (1 / 256)).convert("L") if img.mode.startswith("I") else img.convert("L")
    return img.convert("RGB")  # CMYK, YCbCr, 1 …


def _dpi(img: Image.Image) -> float:
    d = img.info.get("dpi")
    try:
        v = float(d[0]) if d else 0.0
    except (TypeError, ValueError, IndexError):
        v = 0.0
    return v if 36 <= v <= 1200 else 96.0


def iter_images(path: Path) -> Iterator[tuple[bytes, tuple[float, float]]]:
    """Yield ``(encoded_bytes, (width_pt, height_pt))`` for every frame of one image file."""
    try:
        img = Image.open(path)
        img.load() if getattr(img, "n_frames", 1) == 1 else None
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise InvalidInputError(f"'{path.name}' is not a readable image.") from exc
    with img:
        orient_ok = img.getexif().get(0x0112, 1) in (1, None)
        passthrough = img.format == "JPEG" and img.mode in ("RGB", "L") and orient_ok and getattr(img, "n_frames", 1) == 1
        for frame in ImageSequence.Iterator(img):
            frame.load()
            if passthrough:  # keep original JPEG bytes: no re-encoding, no generation loss
                data = path.read_bytes()
                w, h = frame.size
                dpi = _dpi(frame)
            else:
                fr = _normalise(ImageOps.exif_transpose(frame) or frame)
                dpi = _dpi(frame)
                w, h = fr.size
                buf = io.BytesIO()
                fr.save(buf, "PNG", optimize=False)
                data = buf.getvalue()
            yield data, (w * 72 / dpi, h * 72 / dpi)


def _page_geometry(size_pt: tuple[float, float], opt: LayoutOptions) -> tuple[float, float, pymupdf.Rect]:
    iw, ih = size_pt
    m = max(0.0, opt.margin_mm) * MM
    if opt.page_size == "image":
        pw, ph = iw + 2 * m, ih + 2 * m
    else:
        pw, ph = PAGE_SIZES[opt.page_size]
        landscape = (iw > ih) if opt.orientation == "auto" else opt.orientation == "landscape"
        if landscape:
            pw, ph = ph, pw
    aw, ah = pw - 2 * m, ph - 2 * m
    if aw <= 10 or ah <= 10:
        raise InvalidInputError("The margins are too large for this page size.")
    scale = min(aw / iw, ah / ih)
    if opt.placement == "actual":
        scale = min(1.0, scale)
    w, h = iw * scale, ih * scale
    x = m + (aw - w) / 2
    y = m if opt.alignment == "top" else m + (ah - h) / 2
    return pw, ph, pymupdf.Rect(x, y, x + w, y + h)


def images_to_pdf(images: Sequence[Path], output: Path, options: LayoutOptions | None = None, *,
                  overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    ctx = ctx or JobContext()
    opt = options or LayoutOptions()
    images = [Path(p) for p in images]
    if not images:
        raise InvalidInputError("Add at least one image.")
    if opt.page_size not in (*PAGE_SIZES, "image"):
        raise InvalidInputError(f"Unknown page size '{opt.page_size}'.")
    for p in images:
        if p.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise InvalidInputError(f"'{p.name}' is not a supported image type ({', '.join(SUPPORTED_EXTENSIONS)}).")
        if not p.is_file():
            raise InvalidInputError(f"File not found: {p.name}")
    doc = pymupdf.open()
    try:
        for i, p in enumerate(images):
            ctx.step(i, len(images), f"Adding {p.name}")
            for data, size_pt in iter_images(p):
                pw, ph, rect = _page_geometry(size_pt, opt)
                page = doc.new_page(width=pw, height=ph)
                page.insert_image(rect, stream=data, keep_proportion=False)
        with atomic_output(output, overwrite) as tmp:
            ctx.busy("Writing PDF")
            save_pdf(doc, tmp)
        n = doc.page_count
    finally:
        doc.close()
    validate_output_pdf(output, expected_pages=n)
    return Result([Path(output)], f"Created a {n}-page PDF from {len(images)} image file(s).", [], {"pages": n})


# --------------------------------------------------------------------------- tool definition (used by main.py)
def _run(r: Request, ctx: JobContext) -> Result:
    o = r.options
    opt = LayoutOptions(page_size=o["page_size"], orientation=o["orientation"], margin_mm=float(o["margin"]),
                        placement=o["placement"], alignment=o["alignment"])
    return images_to_pdf(r.inputs, r.output, opt, overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="img2pdf", title="Image to PDF", description="Turn JPG, PNG, BMP, TIFF and WebP images into a PDF.",
    category="Convert to PDF", icon="image", input_kind="files", extensions=SUPPORTED_EXTENSIONS, run=_run,
    default_output=lambda i, o: f"{stem(i, 'images')}.pdf", reorderable=True,
    options=(
        Option("page_size", "Page size", "choice", "a4",
               (("A4", "a4"), ("US Letter", "letter"), ("Same as image", "image"))),
        Option("orientation", "Orientation", "choice", "auto",
               (("Automatic", "auto"), ("Portrait", "portrait"), ("Landscape", "landscape")),
               show_if=lambda o: o.get("page_size") != "image"),
        Option("placement", "Image size", "choice", "fit",
               (("Fit to page", "fit"), ("Original size (shrink if too big)", "actual"))),
        Option("alignment", "Position", "choice", "center", (("Centered", "center"), ("Top", "top"))),
        Option("margin", "Margin", "int", 10, minimum=0, maximum=60, suffix=" mm")),
    notice="JPEG files are embedded without re-encoding. Multipage TIFFs create one page per frame.",
    search_terms="jpg png photo picture")
