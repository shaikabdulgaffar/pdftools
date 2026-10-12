"""Extract selected pages into a new PDF."""
from __future__ import annotations

from pathlib import Path

import pymupdf

from .common import (JobContext, Result, atomic_output, copy_metadata, open_pdf, parse_ranges, ranges_to_pages,
                     save_pdf, structure_warnings, validate_output_pdf)


def extract_pages(input_pdf: Path, output: Path, pages_spec: str, *, custom_order: bool = False,
                  overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    """``custom_order=False`` keeps the original page order; ``True`` follows the typed order (repeats allowed)."""
    ctx = ctx or JobContext()
    input_pdf = Path(input_pdf)
    with open_pdf(input_pdf, replacing=output) as src:
        pages = ranges_to_pages(parse_ranges(pages_spec, src.page_count), keep_order=custom_order)
        warnings = structure_warnings(src, input_pdf.name)
        new = pymupdf.open()
        try:
            for i, p in enumerate(pages):
                ctx.step(i, len(pages), f"Copying page {p + 1}")
                new.insert_pdf(src, from_page=p, to_page=p)  # insert_pdf preserves page rotation
            copy_metadata(src, new)
            with atomic_output(output, overwrite) as tmp:
                save_pdf(new, tmp)
        finally:
            new.close()
    validate_output_pdf(output, expected_pages=len(pages))
    return Result([Path(output)], f"Extracted {len(pages)} page(s).", warnings, {"pages": len(pages)})
