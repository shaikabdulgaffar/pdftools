"""Reorder, rotate, delete and duplicate pages according to an explicit plan."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pymupdf

from .common import (InvalidInputError, JobContext, Result, atomic_output, copy_metadata, open_pdf, save_pdf,
                     structure_warnings, validate_output_pdf)


@dataclass(frozen=True)
class PagePlan:
    """One output page: ``source`` is 0-based; ``rotation`` is extra clockwise degrees (0/90/180/270)."""
    source: int
    rotation: int = 0


def organize_pdf(input_pdf: Path, output: Path, plan: Sequence[PagePlan], *, overwrite: bool = False,
                 ctx: JobContext | None = None) -> Result:
    """Build a new PDF whose pages follow ``plan`` (omitted pages are deleted, repeated pages duplicated)."""
    ctx = ctx or JobContext()
    input_pdf = Path(input_pdf)
    if not plan:
        raise InvalidInputError("The page list is empty. Keep at least one page.")
    with open_pdf(input_pdf, replacing=output) as doc:
        n = doc.page_count
        for p in plan:
            if not 0 <= p.source < n:
                raise InvalidInputError(f"Page {p.source + 1} does not exist in this document.")
            if p.rotation % 90:
                raise InvalidInputError("Rotation must be a multiple of 90 degrees.")
        warnings = structure_warnings(doc, input_pdf.name)
        base_rot = [doc[i].rotation for i in range(n)]
        out = pymupdf.open()
        try:
            for i, p in enumerate(plan):
                ctx.step(i, len(plan), f"Placing page {i + 1} of {len(plan)}")
                # One insert per output page => duplicates are independent page objects, so rotating
                # one copy never rotates the other (Document.select would share them).
                out.insert_pdf(doc, from_page=p.source, to_page=p.source)
                if p.rotation % 360:
                    out[i].set_rotation((base_rot[p.source] + p.rotation) % 360)
            copy_metadata(doc, out)
            if doc.get_toc():
                warnings.append("Bookmarks were not carried over because the pages were rearranged.")
            with atomic_output(output, overwrite) as tmp:
                save_pdf(out, tmp)
        finally:
            out.close()
    validate_output_pdf(output, expected_pages=len(plan))
    return Result([Path(output)], f"Saved {len(plan)} page(s).", warnings, {"pages": len(plan)})
