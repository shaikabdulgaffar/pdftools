"""LibreOffice (headless) wrapper used for Word, PowerPoint and Excel → PDF.

We deliberately do not fake these conversions with text extraction.  If
LibreOffice is not installed the caller gets :class:`EngineMissingError`.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

from .common import (ConversionError, EngineMissingError, InvalidInputError, JobContext, Result, atomic_output,
                     log, validate_output_pdf)

INSTALL_HELP = (
    "LibreOffice is required for this conversion but was not found.\n"
    "Install it free from https://www.libreoffice.org/download/ (Windows installer), then restart this app.\n"
    "If it is installed in an unusual place, set the environment variable PDFTOOLKIT_SOFFICE to the full path "
    "of soffice.exe."
)

FONT_NOTE = ("Rendering is done by LibreOffice. Fonts that are not installed on this computer are replaced by "
             "similar ones, so line breaks and page breaks can differ slightly from Microsoft Office.")

# extension -> (required zip member for OOXML sanity check or None)
_OOXML_MARKER = {".docx": "word/document.xml", ".pptx": "ppt/presentation.xml", ".xlsx": "xl/workbook.xml"}


def find_soffice() -> Optional[Path]:
    env = os.environ.get("PDFTOOLKIT_SOFFICE")
    if env and Path(env).is_file():
        return Path(env)
    for name in ("soffice", "soffice.exe", "libreoffice"):
        found = shutil.which(name)
        if found:
            return Path(found)
    roots = [os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"), os.environ.get("LOCALAPPDATA")]
    for root in filter(None, roots):
        cand = Path(root) / "LibreOffice" / "program" / "soffice.exe"
        if cand.is_file():
            return cand
    mac = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
    return mac if mac.is_file() else None


def require_soffice() -> Path:
    exe = find_soffice()
    if exe is None:
        raise EngineMissingError(INSTALL_HELP)
    return exe


def validate_office_file(path: Path, allowed: tuple[str, ...]) -> None:
    """Check extension *and* that OOXML files really are OOXML zip packages."""
    path = Path(path)
    if not path.is_file():
        raise InvalidInputError(f"File not found: {path.name}")
    ext = path.suffix.lower()
    if ext not in allowed:
        raise InvalidInputError(f"'{path.name}' is not supported here. Supported types: {', '.join(allowed)}.")
    if path.stat().st_size == 0:
        raise InvalidInputError(f"'{path.name}' is empty.")
    marker = _OOXML_MARKER.get(ext)
    if marker:
        try:
            with zipfile.ZipFile(path) as zf:
                if marker not in zf.namelist():
                    raise InvalidInputError(f"'{path.name}' is not a valid {ext} document (missing {marker}).")
        except zipfile.BadZipFile as exc:
            raise InvalidInputError(f"'{path.name}' is damaged or is not a real {ext} file. "
                                    "If it is password-protected, remove the password in Office first.") from exc


def libreoffice_to_pdf(src: Path, output: Path, *, overwrite: bool = False, timeout: int = 300,
                       ctx: JobContext | None = None) -> Result:
    ctx = ctx or JobContext()
    src = Path(src)
    exe = require_soffice()
    ctx.busy(f"Converting {src.name} with LibreOffice")
    with tempfile.TemporaryDirectory(prefix="pdftoolkit_") as work_s:
        work = Path(work_s)
        # Work on a copy with a neutral name: the original is never opened by the engine and odd file names
        # cannot confuse the command line.
        local = work / f"input{src.suffix.lower()}"
        shutil.copyfile(src, local)
        profile = work / "profile"  # private profile: no clash with a running LibreOffice, no user settings
        cmd = [str(exe), f"-env:UserInstallation={profile.as_uri()}", "--headless", "--norestore", "--nolockcheck",
               "--nodefault", "--nologo", "--convert-to", "pdf", "--outdir", str(work), str(local)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                    creationflags=flags)
        except OSError as exc:
            raise EngineMissingError(f"LibreOffice could not be started: {exc}\n\n{INSTALL_HELP}") from exc
        start = time.monotonic()
        try:
            while proc.poll() is None:
                ctx.check()
                if time.monotonic() - start > timeout:
                    raise ConversionError(f"LibreOffice took longer than {timeout} s and was stopped. "
                                          "The document may be very large or contain unsupported content.")
                time.sleep(0.2)
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        stderr = (proc.stderr.read() or b"").decode("utf-8", "replace")[:500] if proc.stderr else ""
        produced = work / "input.pdf"
        if proc.returncode != 0 or not produced.is_file():
            log.error("LibreOffice failed rc=%s", proc.returncode)  # no document content is logged
            raise ConversionError("LibreOffice could not convert this file. It may be corrupt, "
                                  "password-protected or use unsupported features."
                                  + (f"\nEngine message: {stderr.strip()}" if stderr.strip() else ""))
        with atomic_output(output, overwrite) as tmp:
            shutil.copyfile(produced, tmp)
    pages = validate_output_pdf(output)
    return Result([Path(output)], f"Converted to a {pages}-page PDF.", [FONT_NOTE], {"pages": pages})
