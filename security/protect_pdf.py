"""Protect PDF - AES-256 encryption with optional owner permissions."""
from __future__ import annotations

import pymupdf
from pathlib import Path
from typing import Optional

from utils import (
    InvalidInputError, JobContext, Option, PDF_EXT, Request, Result, ToolDef, atomic_output,
    open_pdf, save_pdf, stem, structure_warnings, validate_output_pdf,
)


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


# --------------------------------------------------------------------------- tool definition (used by main.py)
def _check(inputs, o):
    if not o.get("password"):
        return "Enter a password to open the PDF."
    if o["password"] != o.get("confirm"):
        return "The two passwords do not match."
    if o.get("owner") and o["owner"] == o["password"]:
        return "Use a different owner password, or leave it empty (an identical one gives no real restrictions)."
    return None


def _run(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return protect_pdf(r.inputs[0], r.output, o["password"], o.get("owner") or None, allow_print=o["allow_print"],
                       allow_copy=o["allow_copy"], allow_modify=o["allow_modify"],
                       allow_annotate=o["allow_annotate"], overwrite=r.overwrite, ctx=ctx)


TOOL = ToolDef(
    id="protect", title="Protect PDF", description="Encrypt a PDF with AES-256 and set permissions.",
    category="Security", icon="lock", input_kind="file", extensions=PDF_EXT, run=_run,
    default_output=lambda i, o: f"{stem(i)}_protected.pdf",
    options=(
        Option("password", "Open password", "password", "", placeholder="Required to open the file"),
        Option("confirm", "Confirm password", "password", ""),
        Option("owner", "Owner password (optional)", "password", "", placeholder="Needed to change the permissions",
               tooltip="Use a different password from the open password, or restrictions are meaningless."),
        Option("allow_print", "Allow printing", "bool", True),
        Option("allow_copy", "Allow copying text", "bool", True),
        Option("allow_modify", "Allow editing", "bool", True),
        Option("allow_annotate", "Allow comments & annotations", "bool", True)),
    notice="Permissions are a courtesy honoured by compliant software; they do not prevent screenshots or determined "
           "copying. Only the open password keeps content private. If you forget it, the file cannot be recovered.",
    validate=_check, search_terms="encrypt password secure")
