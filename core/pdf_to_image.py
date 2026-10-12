"""Render PDF pages to PNG or JPEG files."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image

from .common import (InvalidInputError, JobContext, Result, atomic_output, check_no_collisions, check_output_dir,
                     open_pdf, parse_ranges, ranges_to_pages, sanitize_filename)

DPI_PRESETS = {"Screen (72 dpi)": 72, "Standard (150 dpi)": 150, "High (300 dpi)": 300, "Print (600 dpi)": 600}
MAX_PIXELS = 120_000_000  # guards against runaway memory use


def pdf_to_images(input_pdf: Path, output_dir: Path, *, fmt: str = "png", dpi: int = 150, jpeg_quality: int = 90,
                  pages_spec: str = "", password: Optional[str] = None, overwrite: bool = False,
                  ctx: JobContext | None = None) -> Result:
    """``pages_spec`` empty = all pages. Files are named ``<stem>_page_001.png``."""
    ctx = ctx or JobContext()
    fmt = fmt.lower().replace("jpg", "jpeg")
    if fmt not in ("png", "jpeg"):
        raise InvalidInputError("Format must be PNG or JPEG.")
    if not 36 <= dpi <= 1200:
        raise InvalidInputError("Resolution must be between 36 and 1200 dpi.")
    input_pdf = Path(input_pdf)
    out_dir = check_output_dir(output_dir)
    ext = "png" if fmt == "png" else "jpg"
    with open_pdf(input_pdf, password=password, allow_protected=True) as doc:
        n = doc.page_count
        pages = ranges_to_pages(parse_ranges(pages_spec, n)) if pages_spec.strip() else list(range(n))
        width = max(3, len(str(n)))
        stem = sanitize_filename(input_pdf.stem, "document")
        targets = [out_dir / f"{stem}_page_{p + 1:0{width}d}.{ext}" for p in pages]
        check_no_collisions(targets, overwrite)
        for i, (p, target) in enumerate(zip(pages, targets)):
            ctx.step(i, len(pages), f"Rendering page {p + 1}")
            page = doc[p]
            w, h = page.rect.width * dpi / 72, page.rect.height * dpi / 72
            if w * h > MAX_PIXELS:
                raise InvalidInputError(f"Page {p + 1} would be {w:.0f}×{h:.0f} pixels at {dpi} dpi. Choose a lower resolution.")
            pix = page.get_pixmap(dpi=dpi, alpha=False)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            with atomic_output(target, overwrite) as tmp:
                if fmt == "png":
                    img.save(tmp, "PNG", dpi=(dpi, dpi))
                else:
                    img.save(tmp, "JPEG", quality=jpeg_quality, optimize=True, dpi=(dpi, dpi))
            with Image.open(target) as check:  # verify the image really decodes
                check.load()
    return Result(targets, f"Exported {len(targets)} image(s) to '{out_dir}'.", [], {"count": len(targets)})
