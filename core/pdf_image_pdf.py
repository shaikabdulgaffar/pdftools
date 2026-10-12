"""Rasterise every page and rebuild a PDF from the images (flatten)."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from .common import JobContext, Result, atomic_output, open_pdf, save_pdf, size_change, validate_output_pdf

RASTER_WARNING = ("Every page becomes a picture. Selectable/searchable text, links, form fields, bookmarks and "
                  "vector graphics are lost, and the file may be larger.")


def pdf_to_image_to_pdf(input_pdf: Path, output: Path, *, dpi: int = 150, fmt: str = "jpeg", jpeg_quality: int = 80,
                        overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    """Pages are rendered one at a time and streamed into the new PDF (low memory use);
    the page size of every output page equals the source page size in points."""
    ctx = ctx or JobContext()
    fmt = fmt.lower()
    input_pdf = Path(input_pdf)
    with open_pdf(input_pdf, replacing=output) as src:
        n = src.page_count
        out = pymupdf.open()
        try:
            for i in range(n):
                ctx.step(i, n, f"Rasterising page {i + 1} of {n}")
                page = src[i]
                pix = page.get_pixmap(dpi=dpi, alpha=False)
                data = pix.tobytes("jpeg", jpg_quality=jpeg_quality) if fmt == "jpeg" else pix.tobytes("png")
                new = out.new_page(width=page.rect.width, height=page.rect.height)
                new.insert_image(new.rect, stream=data)
                del pix, data
            ctx.busy("Writing PDF")
            with atomic_output(output, overwrite) as tmp:
                save_pdf(out, tmp)
        finally:
            out.close()
    validate_output_pdf(output, expected_pages=n)
    before, after = input_pdf.stat().st_size, Path(output).stat().st_size
    return Result([Path(output)], f"Rasterised {n} page(s): {size_change(before, after)}.", [RASTER_WARNING],
                  {"pages": n, "before": before, "after": after})
