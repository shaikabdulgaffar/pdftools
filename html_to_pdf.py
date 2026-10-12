"""HTML to PDF - local HTML file or pasted HTML, rendered offline by PyMuPDF."""
from __future__ import annotations

import pymupdf
import re
from pathlib import Path
from typing import Optional

from utils import (
    ConversionError, InvalidInputError, JobContext, Option, Request, Result, ToolDef, atomic_output,
    stem, validate_output_pdf,
)


MM = 72 / 25.4
MAX_PAGES = 3000
ENGINE_NOTE = ("Rendered by PyMuPDF's HTML engine: it supports common HTML and a subset of CSS (no JavaScript, "
               "limited flexbox/grid, no web fonts). Complex modern pages may look different from a browser.")


def scan_html(html: str, base_dir: Optional[Path]) -> list[str]:
    """Return warnings about content the engine cannot or will not load."""
    warns: list[str] = []
    if re.search(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//""", html, re.I) or re.search(r"url\(\s*['\"]?\s*https?:", html, re.I) \
            or re.search(r"@import\s+(?:url\()?['\"]?https?:", html, re.I):
        warns.append("The HTML refers to external (online) resources. Nothing is downloaded, so they are missing.")
    if re.search(r"<script\b", html, re.I):
        warns.append("Scripts are not executed; content that JavaScript would create will be missing.")
    if re.search(r"""(?:src|href)\s*=\s*["']?\.\./""", html, re.I) or re.search(r"url\(\s*['\"]?\.\./", html, re.I):
        warns.append("Resources outside the HTML file's folder ('../') are not loaded for safety.")
    if base_dir is None:
        warns.append("No base folder: local images and stylesheets referenced by the HTML cannot be found.")
    return warns


def html_to_pdf(output: Path, *, html_file: Optional[Path] = None, html_text: Optional[str] = None,
                page_size: str = "a4", orientation: str = "portrait", margin_mm: float = 15.0,
                overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    """Provide either ``html_file`` (its folder is used for relative resources) or ``html_text``."""
    ctx = ctx or JobContext()
    base_dir: Optional[Path] = None
    if html_file is not None:
        html_file = Path(html_file)
        if html_file.suffix.lower() not in (".html", ".htm", ".xhtml"):
            raise InvalidInputError(f"'{html_file.name}' is not an HTML file.")
        if not html_file.is_file():
            raise InvalidInputError(f"File not found: {html_file.name}")
        raw = html_file.read_bytes()
        try:
            html = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            html = raw.decode("cp1252", errors="replace")
        base_dir = html_file.parent
    elif html_text is not None:
        html = html_text
    else:
        raise InvalidInputError("Choose an HTML file or paste HTML content.")
    if not html.strip():
        raise InvalidInputError("The HTML content is empty.")
    sizes = {"a4": (595.0, 842.0), "letter": (612.0, 792.0)}
    if page_size not in sizes:
        raise InvalidInputError(f"Unknown page size '{page_size}'.")
    pw, ph = sizes[page_size]
    if orientation == "landscape":
        pw, ph = ph, pw
    margin = max(0.0, margin_mm) * MM
    where = pymupdf.Rect(margin, margin, pw - margin, ph - margin)
    if where.width < 50 or where.height < 50:
        raise InvalidInputError("The margins are too large for this page size.")
    warnings = scan_html(html, base_dir) + [ENGINE_NOTE]
    ctx.busy("Rendering HTML")
    try:
        archive = pymupdf.Archive(str(base_dir)) if base_dir else None
        story = pymupdf.Story(html=html, archive=archive)
    except Exception as exc:
        raise ConversionError("The HTML could not be parsed by the rendering engine.") from exc
    with atomic_output(output, overwrite) as tmp:
        writer = pymupdf.DocumentWriter(str(tmp))
        pages = 0
        try:
            more = 1
            while more:
                ctx.check()
                dev = writer.begin_page(pymupdf.Rect(0, 0, pw, ph))
                more, _filled = story.place(where)
                story.draw(dev)
                writer.end_page()
                pages += 1
                if pages >= MAX_PAGES:
                    raise ConversionError(f"Stopped after {MAX_PAGES} pages; the content cannot be laid out.")
        finally:
            writer.close()
    validate_output_pdf(output, expected_pages=pages)
    return Result([Path(output)], f"Created a {pages}-page PDF.", warnings, {"pages": pages})


# --------------------------------------------------------------------------- tool definition (used by main.py)
def _run(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return html_to_pdf(r.output, html_file=r.inputs[0] if r.inputs else None, html_text=r.html_text,
                       page_size=o["page_size"], orientation=o["orientation"], margin_mm=float(o["margin"]),
                       overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="html2pdf", title="HTML to PDF", description="Convert a local HTML file, or HTML you paste, into a PDF.",
    category="Convert to PDF", icon="html", input_kind="html", extensions=(".html", ".htm", ".xhtml"), run=_run,
    default_output=lambda i, o: f"{stem(i, 'webpage')}.pdf",
    options=(
        Option("page_size", "Page size", "choice", "a4", (("A4", "a4"), ("US Letter", "letter"))),
        Option("orientation", "Orientation", "choice", "portrait", (("Portrait", "portrait"), ("Landscape", "landscape"))),
        Option("margin", "Margin", "int", 15, minimum=0, maximum=60, suffix=" mm")),
    notice="Works offline. Supports common HTML and a subset of CSS; JavaScript, web fonts and online resources "
           "are not available.", search_terms="web page website")
