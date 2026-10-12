"""Merge PDFs in the exact order given."""
from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pymupdf

from .common import (InvalidInputError, JobContext, Result, atomic_output, copy_metadata, log, open_pdf,
                     save_pdf, structure_warnings, validate_output_pdf)


def merge_pdfs(inputs: Sequence[Path], output: Path, *, overwrite: bool = False,
               ctx: JobContext | None = None) -> Result:
    ctx = ctx or JobContext()
    inputs = [Path(p) for p in inputs]
    if len(inputs) < 2:
        raise InvalidInputError("Add at least two PDF files to merge.")
    out = pymupdf.open()
    warnings: list[str] = []
    toc: list[list] = []
    total = 0
    try:
        for i, path in enumerate(inputs):
            ctx.step(i, len(inputs), f"Merging {path.name}")
            with open_pdf(path) as src:
                warnings += structure_warnings(src, path.name)
                if i == 0:
                    copy_metadata(src, out)
                try:
                    toc += [[lvl, title, pg + total] for lvl, title, pg in src.get_toc() if pg > 0]
                except Exception:
                    log.debug("toc read failed", exc_info=True)
                out.insert_pdf(src)  # keeps page order, rotation, links, annotations
                total += src.page_count
        if toc:
            try:
                out.set_toc(toc)
            except Exception:
                warnings.append("Bookmarks from the source files could not be combined and were dropped.")
        ctx.busy("Writing merged PDF")
        with atomic_output(output, overwrite) as tmp:
            save_pdf(out, tmp)
    finally:
        out.close()
    pages = validate_output_pdf(output, expected_pages=total)
    return Result([Path(output)], f"Merged {len(inputs)} files into {pages} pages.", warnings, {"pages": pages})
