"""Split PDF - single pages, custom ranges, or chunks of N pages."""
from __future__ import annotations

import pymupdf
from pathlib import Path

from utils import (
    InvalidInputError, JobContext, Option, PDF_EXT, Request, Result, ToolDef, atomic_output,
    check_no_collisions, check_output_dir, copy_metadata, open_pdf, parse_ranges, sanitize_filename,
    save_pdf, stem, structure_warnings, validate_output_pdf,
)


def plan_split(page_count: int, mode: str, ranges_spec: str = "", every_n: int = 1) -> list[tuple[int, int]]:
    """Return 1-based inclusive (start, end) chunks for the chosen mode."""
    if mode == "pages":
        return [(p, p) for p in range(1, page_count + 1)]
    if mode == "ranges":
        return parse_ranges(ranges_spec, page_count)
    if mode == "every":
        if every_n < 1:
            raise InvalidInputError("'Every N pages' must be 1 or more.")
        return [(s, min(s + every_n - 1, page_count)) for s in range(1, page_count + 1, every_n)]
    raise InvalidInputError(f"Unknown split mode '{mode}'.")


def split_pdf(input_pdf: Path, output_dir: Path, *, mode: str = "pages", ranges_spec: str = "",
              every_n: int = 1, overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    ctx = ctx or JobContext()
    input_pdf = Path(input_pdf)
    out_dir = check_output_dir(output_dir)
    with open_pdf(input_pdf) as src:
        chunks = plan_split(src.page_count, mode, ranges_spec, every_n)
        width = max(3, len(str(src.page_count)))
        stem = sanitize_filename(input_pdf.stem, "document")
        names = [out_dir / (f"{stem}_page_{a:0{width}d}.pdf" if a == b
                            else f"{stem}_pages_{a:0{width}d}-{b:0{width}d}.pdf") for a, b in chunks]
        if len(set(names)) != len(names):
            raise InvalidInputError("Some ranges overlap exactly and would create the same file name.")
        check_no_collisions(names, overwrite)  # fail before writing anything
        warnings = structure_warnings(src, input_pdf.name)
        outputs: list[Path] = []
        for i, ((a, b), target) in enumerate(zip(chunks, names)):
            ctx.step(i, len(chunks), f"Writing {target.name}")
            part = pymupdf.open()
            try:
                part.insert_pdf(src, from_page=a - 1, to_page=b - 1)
                copy_metadata(src, part)
                with atomic_output(target, overwrite) as tmp:
                    save_pdf(part, tmp)
            finally:
                part.close()
            validate_output_pdf(target, expected_pages=b - a + 1)
            outputs.append(target)
    return Result(outputs, f"Created {len(outputs)} PDF file(s) in '{out_dir}'.", warnings, {"count": len(outputs)})


# --------------------------------------------------------------------------- tool definition (used by main.py)
def _run(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return split_pdf(r.inputs[0], r.output, mode=o["mode"], ranges_spec=o.get("ranges", ""),
                     every_n=o.get("every_n", 1), overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="split", title="Split PDF", description="Cut a PDF into single pages, page ranges, or chunks of N pages.",
    category="PDF Management", icon="split", input_kind="file", extensions=PDF_EXT, run=_run,
    default_output=lambda i, o: f"{stem(i)}_split",
    options=(
        Option("mode", "Split mode", "choice", "pages",
               (("Every page as its own file", "pages"), ("Custom page ranges", "ranges"), ("Every N pages", "every"))),
        Option("ranges", "Ranges", "text", "", placeholder="e.g. 1-3, 5, 8-10",
               show_if=lambda o: o.get("mode") == "ranges", tooltip="Each range becomes its own PDF."),
        Option("every_n", "Pages per file", "int", 5, minimum=1, maximum=10000,
               show_if=lambda o: o.get("mode") == "every")),
    output_kind="folder", search_terms="separate divide cut")
