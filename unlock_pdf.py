"""Unlock PDF - save an unprotected copy; a valid password is required."""
from __future__ import annotations

import pymupdf
from pathlib import Path

from utils import (
    InvalidInputError, JobContext, Option, PDF_EXT, PasswordRequiredError, Request, Result, ToolDef,
    WrongPasswordError, atomic_output, is_restricted, load_pdf_raw, save_pdf, stem,
    structure_warnings, validate_output_pdf,
)


def unlock_pdf(input_pdf: Path, output: Path, password: str, *, overwrite: bool = False,
               ctx: JobContext | None = None) -> Result:
    """Save an unprotected copy. Requires a *valid* password; never attempts to guess or bypass one.

    * Open-password PDFs: the password must authenticate (user or owner).
    * Permission-only PDFs (no open password): the *owner* password must authenticate.
    """
    ctx = ctx or JobContext()
    input_pdf = Path(input_pdf)
    if not password:
        raise PasswordRequiredError("Enter the PDF's password.")
    doc = load_pdf_raw(input_pdf, replacing=output)
    try:
        if doc.needs_pass:
            if not doc.authenticate(password):  # 0 = wrong; 2 = user pw; 4 = owner pw
                raise WrongPasswordError("That password is incorrect. Nothing was unlocked.")
        elif is_restricted(doc):
            if not (doc.authenticate(password) & 4):
                raise WrongPasswordError("This PDF opens freely but has permission restrictions. "
                                         "The owner password is required to remove them.")
        else:
            raise InvalidInputError(f"'{input_pdf.name}' is not password-protected; there is nothing to unlock.")
        n = doc.page_count
        warnings = structure_warnings(doc, input_pdf.name)
        ctx.busy("Saving unlocked copy")
        with atomic_output(output, overwrite) as tmp:
            save_pdf(doc, tmp, encryption=pymupdf.PDF_ENCRYPT_NONE)
    finally:
        doc.close()
    validate_output_pdf(output, expected_pages=n)
    with pymupdf.open(output) as check:
        if check.needs_pass or is_restricted(check):
            raise InvalidInputError("Output verification failed: the copy is still protected.")
    return Result([Path(output)], "Saved an unlocked copy. Keep it somewhere private if the content is sensitive.",
                  warnings, {"pages": n})


# --------------------------------------------------------------------------- tool definition (used by main.py)
def _run(r: Request, ctx: JobContext) -> Result:
    return unlock_pdf(r.inputs[0], r.output, r.options.get("password", ""), overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="unlock", title="Unlock PDF", description="Remove protection from a PDF - you must know its password.",
    category="Security", icon="unlock", input_kind="file", extensions=PDF_EXT, run=_run,
    default_output=lambda i, o: f"{stem(i)}_unlocked.pdf",
    options=(Option("password", "Password", "password", "", placeholder="The PDF's password"),),
    notice="For files you are authorised to modify. This tool cannot recover or guess forgotten passwords.",
    validate=lambda i, o: None if o.get("password") else "Enter the PDF's password.",
    search_terms="decrypt remove password")
