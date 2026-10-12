"""PowerPoint to PDF - one PDF page per slide, rendered by LibreOffice."""
from __future__ import annotations

from pathlib import Path

from utils import (
    JobContext, Request, Result, ToolDef, libreoffice_to_pdf, stem, validate_office_file,
)


SUPPORTED = (".pptx", ".ppt", ".odp")


def powerpoint_to_pdf(src: Path, output: Path, *, overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    """One PDF page per slide (LibreOffice's default slide export)."""
    validate_office_file(src, SUPPORTED)
    res = libreoffice_to_pdf(src, output, overwrite=overwrite, ctx=ctx)
    res.warnings.append("Transitions, animations, audio and video are not part of a PDF. SmartArt, charts and "
                        "special fonts may render differently from PowerPoint.")
    return res


# --------------------------------------------------------------------------- tool definition (used by main.py)
def _run(r: Request, ctx: JobContext) -> Result:
    return powerpoint_to_pdf(r.inputs[0], r.output, overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="ppt2pdf", title="PowerPoint to PDF", description="One PDF page per slide, rendered by LibreOffice.",
    category="Convert to PDF", icon="ppt", input_kind="file", extensions=SUPPORTED, run=_run,
    default_output=lambda i, o: f"{stem(i)}.pdf",
    notice="Requires LibreOffice (free). Animations and transitions do not exist in PDF.",
    search_terms="pptx slides presentation deck")
