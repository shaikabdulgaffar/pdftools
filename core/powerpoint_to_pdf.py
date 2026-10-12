from __future__ import annotations

from pathlib import Path

from .common import JobContext, Result
from .office_engine import libreoffice_to_pdf, validate_office_file

SUPPORTED = (".pptx", ".ppt", ".odp")


def powerpoint_to_pdf(src: Path, output: Path, *, overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    """One PDF page per slide (LibreOffice's default slide export)."""
    validate_office_file(src, SUPPORTED)
    res = libreoffice_to_pdf(src, output, overwrite=overwrite, ctx=ctx)
    res.warnings.append("Transitions, animations, audio and video are not part of a PDF. SmartArt, charts and "
                        "special fonts may render differently from PowerPoint.")
    return res
