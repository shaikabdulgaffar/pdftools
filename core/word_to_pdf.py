from __future__ import annotations

from pathlib import Path

from .common import JobContext, Result
from .office_engine import libreoffice_to_pdf, validate_office_file

SUPPORTED = (".docx", ".doc", ".odt")  # .docx is the tested baseline; .doc/.odt are handled by LibreOffice itself


def word_to_pdf(src: Path, output: Path, *, overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    validate_office_file(src, SUPPORTED)
    res = libreoffice_to_pdf(src, output, overwrite=overwrite, ctx=ctx)
    res.warnings.append("Embedded macros are not executed. Complex layouts, text boxes, fields and "
                        "embedded objects may differ from Word.")
    return res
