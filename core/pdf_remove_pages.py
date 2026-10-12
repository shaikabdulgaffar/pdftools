"""Remove pages from a PDF and save a new file."""
from __future__ import annotations

from pathlib import Path

from .common import (InvalidInputError, JobContext, Result, atomic_output, copy_metadata, open_pdf, parse_ranges,
                     ranges_to_pages, save_pdf, structure_warnings, validate_output_pdf)


def page_count(path: Path) -> int:
    with open_pdf(path) as d:
        return d.page_count


def remove_pages(input_pdf: Path, output: Path, pages_spec: str, *, overwrite: bool = False,
                 ctx: JobContext | None = None) -> Result:
    ctx = ctx or JobContext()
    input_pdf = Path(input_pdf)
    with open_pdf(input_pdf, replacing=output) as doc:
        n = doc.page_count
        remove = ranges_to_pages(parse_ranges(pages_spec, n))
        if len(remove) >= n:
            raise InvalidInputError("You cannot remove every page. Leave at least one page in the document.")
        warnings = structure_warnings(doc, input_pdf.name)
        ctx.busy("Removing pages")
        doc.delete_pages(remove)
        with atomic_output(output, overwrite) as tmp:
            save_pdf(doc, tmp)  # metadata is kept because we edit the original document object
    pages = validate_output_pdf(output, expected_pages=n - len(remove))
    return Result([Path(output)], f"Removed {len(remove)} page(s); {pages} page(s) remain.", warnings,
                  {"pages": pages, "removed": len(remove)})
