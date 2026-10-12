"""Remove Pages - delete pages and save a new PDF."""
from __future__ import annotations

from pathlib import Path

from utils import (
    InvalidInputError, JobContext, Option, PDF_EXT, Request, Result, ToolDef, atomic_output,
    open_pdf, parse_ranges, ranges_to_pages, save_pdf, stem, structure_warnings, validate_output_pdf,
)


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


# --------------------------------------------------------------------------- tool definition (used by main.py)
def _run(r: Request, ctx: JobContext) -> Result:
    return remove_pages(r.inputs[0], r.output, r.options["pages"], overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="remove", title="Remove Pages", description="Delete unwanted pages and save a new PDF.",
    category="PDF Management", icon="remove", input_kind="file", extensions=PDF_EXT, run=_run,
    default_output=lambda i, o: f"{stem(i)}_removed.pdf",
    options=(Option("pages", "Pages", "text", "", placeholder="e.g. 1-3, 5, 8-10",
           tooltip="Page numbers and ranges separated by commas. Selecting thumbnails fills this in."),),
    viewer="select", search_terms="delete pages")
