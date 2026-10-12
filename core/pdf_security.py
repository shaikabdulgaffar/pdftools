"""Password-protect and unlock PDFs (authorised use only)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pymupdf

from .common import (InvalidInputError, JobContext, PasswordRequiredError, Result, WrongPasswordError,
                     atomic_output, is_restricted, load_pdf_raw, open_pdf, save_pdf, structure_warnings,
                     validate_output_pdf)

PERMISSION_NOTE = ("Permission restrictions (printing, copying, editing) are enforced only by compliant PDF "
                   "software. They do not stop screenshots, photographing the screen, or tools that ignore them. "
                   "The open-password is the only protection that keeps content private.")


def protect_pdf(input_pdf: Path, output: Path, user_password: str, owner_password: Optional[str] = None, *,
                allow_print: bool = True, allow_copy: bool = True, allow_modify: bool = True,
                allow_annotate: bool = True, overwrite: bool = False, ctx: JobContext | None = None) -> Result:
    """AES-256 encryption. ``user_password`` is needed to open; ``owner_password`` controls permissions.

    If ``owner_password`` is omitted the user password is reused, which means anyone who can open the
    file holds owner rights and the permission flags have no practical effect.
    """
    ctx = ctx or JobContext()
    if not user_password:
        raise InvalidInputError("Enter a password to open the PDF.")
    owner = owner_password or user_password
    perms = pymupdf.PDF_PERM_ACCESSIBILITY | pymupdf.PDF_PERM_ASSEMBLE  # accessibility is always kept on
    if allow_print:
        perms |= pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    if allow_copy:
        perms |= pymupdf.PDF_PERM_COPY
    if allow_modify:
        perms |= pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_FORM
    if allow_annotate:
        perms |= pymupdf.PDF_PERM_ANNOTATE
    input_pdf = Path(input_pdf)
    with open_pdf(input_pdf, replacing=output) as doc:
        n = doc.page_count
        warnings = structure_warnings(doc, input_pdf.name)
        if owner == user_password and not (allow_print and allow_copy and allow_modify and allow_annotate):
            warnings.append("The owner password equals the open password, so restrictions can be lifted by anyone "
                            "who opens the file. Use a different owner password for real restrictions.")
        warnings.append(PERMISSION_NOTE)
        ctx.busy("Encrypting")
        with atomic_output(output, overwrite) as tmp:
            save_pdf(doc, tmp, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw=user_password,
                     owner_pw=owner, permissions=perms)
    validate_output_pdf(output, expected_pages=n, password=user_password)
    with pymupdf.open(output) as check:  # must genuinely demand the password
        if not check.needs_pass:
            raise InvalidInputError("Output verification failed: the file does not require a password.")
    return Result([Path(output)], "Created an AES-256 encrypted copy.", warnings, {"pages": n})


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
