"""Word to PDF - rendered by LibreOffice (installed separately)."""
from __future__ import annotations

from pathlib import Path

from utils import (
    JobContext, Request, Result, ToolDef, libreoffice_to_pdf, stem, validate_office_file,
)


SUPPORTED = (".docx", ".doc", ".odt")  # .docx is the tested baseline; .doc/.odt are handled by LibreOffice itself


def word_to_pdf(src: Path, output: Path, *, overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    validate_office_file(src, SUPPORTED)
    res = libreoffice_to_pdf(src, output, overwrite=overwrite, ctx=ctx)
    res.warnings.append("Embedded macros are not executed. Complex layouts, text boxes, fields and "
                        "embedded objects may differ from Word.")
    return res


# --------------------------------------------------------------------------- tool definition (used by main.py)
def _run(r: Request, ctx: JobContext) -> Result:
    return word_to_pdf(r.inputs[0], r.output, overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="word2pdf", title="Word to PDF", description="Convert Word documents to PDF with the LibreOffice engine.",
    category="Convert to PDF", icon="word", input_kind="file", extensions=SUPPORTED, run=_run,
    default_output=lambda i, o: f"{stem(i)}.pdf",
    notice="Requires LibreOffice (free). Layout is rendered by LibreOffice, so fonts and spacing can differ "
           "slightly from Microsoft Word.", search_terms="docx doc office")
