"""PDF to Image to PDF - rasterise every page and rebuild a flattened PDF."""
from __future__ import annotations

import pymupdf
from pathlib import Path

from utils import (
    JobContext, Option, PDF_EXT, Request, Result, ToolDef, atomic_output, open_pdf, save_pdf,
    size_change, stem, validate_output_pdf,
)


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


# --------------------------------------------------------------------------- tool definition (used by main.py)
DPI_PRESETS = {"Screen (72 dpi)": 72, "Standard (150 dpi)": 150, "High (300 dpi)": 300, "Print (600 dpi)": 600}


def _run(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return pdf_to_image_to_pdf(r.inputs[0], r.output, dpi=int(o["dpi"]), fmt=o["format"],
                               jpeg_quality=int(o["quality"]), overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="rasterize", title="PDF to Image to PDF",
    description="Flatten a PDF: every page becomes a picture inside a new PDF.",
    category="Convert from PDF", icon="raster", input_kind="file", extensions=PDF_EXT, run=_run,
    default_output=lambda i, o: f"{stem(i)}_rasterized.pdf",
    options=(
        Option("dpi", "Resolution", "choice", 150, tuple(DPI_PRESETS.items())),
        Option("format", "Image type", "choice", "jpeg", (("JPEG (smaller)", "jpeg"), ("PNG (lossless)", "png"))),
        Option("quality", "JPEG quality", "int", 80, minimum=10, maximum=100,
               show_if=lambda o: o.get("format") == "jpeg")),
    notice="Rasterization warning: text becomes a picture. Selectable and searchable text, links, forms, bookmarks "
           "and vector graphics are lost, and the file may get larger. Useful for flattening scans or removing "
           "hidden layers.", search_terms="flatten scan print")
