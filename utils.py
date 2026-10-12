"""Shared code used by every feature file: errors, progress/cancel, page ranges, safe output writing,
PDF opening/validation, the LibreOffice helper, and the tool-definition dataclasses.

Nothing here imports Qt, so every feature file works (and can be tested) without the GUI.
"""
from __future__ import annotations

import errno
import logging
import os
import re
import sys
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence

import pymupdf

log = logging.getLogger("pdf_toolkit")

PAGE_PERM_MASK = (
    pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_MODIFY | pymupdf.PDF_PERM_COPY | pymupdf.PDF_PERM_ANNOTATE
)


# --------------------------------------------------------------------------- errors
class ToolkitError(Exception):
    """Base class. ``str(exc)`` is always safe to show to the user."""


class InvalidInputError(ToolkitError): ...
class PasswordRequiredError(ToolkitError): ...
class WrongPasswordError(ToolkitError): ...
class EngineMissingError(ToolkitError): ...
class ConversionError(ToolkitError): ...
class OutputError(ToolkitError): ...
class OperationCancelled(ToolkitError): ...


class OutputExistsError(ToolkitError):
    """Raised *before* any work is done when a target already exists."""

    def __init__(self, paths: Sequence[Path]):
        self.paths = [Path(p) for p in paths]
        shown = ", ".join(p.name for p in self.paths[:3]) + (" …" if len(self.paths) > 3 else "")
        super().__init__(f"Output already exists: {shown}")


# ----------------------------------------------------------------- progress / cancel
class CancelToken:
    def __init__(self) -> None:
        self._ev = threading.Event()

    def cancel(self) -> None:
        self._ev.set()

    @property
    def cancelled(self) -> bool:
        return self._ev.is_set()


ProgressFn = Callable[[int, int, str], None]


@dataclass
class JobContext:
    """Carries progress reporting and cancellation into a core function."""

    progress: Optional[ProgressFn] = None
    cancel: CancelToken = field(default_factory=CancelToken)

    def check(self) -> None:
        if self.cancel.cancelled:
            raise OperationCancelled("The operation was cancelled.")

    def step(self, done: int, total: int, message: str = "") -> None:
        """Check for cancellation, then report ``done`` of ``total`` steps."""
        self.check()
        if self.progress:
            self.progress(done, total, message)

    def busy(self, message: str = "") -> None:
        """Report an operation whose length cannot be known (indeterminate bar)."""
        self.check()
        if self.progress:
            self.progress(0, 0, message)


@dataclass
class Result:
    outputs: list[Path] = field(default_factory=list)
    message: str = ""
    warnings: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------- page ranges
_RANGE_RE = re.compile(r"(\d+)\s*(?:-\s*(\d+))?")


def parse_ranges(spec: str, page_count: int) -> list[tuple[int, int]]:
    """Parse ``"1-3, 5, 8-10"`` into validated, 1-based inclusive ``(start, end)`` tuples."""
    if spec is None or not spec.strip():
        raise InvalidInputError("Enter at least one page number or range, for example 1-3, 5, 8-10.")
    out: list[tuple[int, int]] = []
    for part in re.split(r"[,;]", spec):
        part = part.strip()
        if not part:
            continue
        m = _RANGE_RE.fullmatch(part)
        if not m:
            raise InvalidInputError(f"'{part}' is not a valid page or range. Use numbers like 3 or 2-6.")
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else start
        if start < 1 or end < 1:
            raise InvalidInputError("Page numbers start at 1.")
        if start > end:
            raise InvalidInputError(f"Range '{part}' is backwards. Write it as {end}-{start}.")
        if end > page_count:
            raise InvalidInputError(f"Page {end} does not exist. This document has {page_count} page(s).")
        out.append((start, end))
    if not out:
        raise InvalidInputError("Enter at least one page number or range.")
    return out


def ranges_to_pages(ranges: Sequence[tuple[int, int]], *, keep_order: bool = False) -> list[int]:
    """Flatten ranges to 0-based page indexes.

    ``keep_order=False`` returns unique pages in document order;
    ``keep_order=True`` keeps the typed order and allows repeats.
    """
    pages = [p - 1 for a, b in ranges for p in range(a, b + 1)]
    return pages if keep_order else sorted(set(pages))


def pages_to_spec(pages: Sequence[int]) -> str:
    """Inverse helper for the GUI: [0,1,2,4] -> "1-3, 5"."""
    pages = sorted(set(pages))
    parts: list[str] = []
    i = 0
    while i < len(pages):
        j = i
        while j + 1 < len(pages) and pages[j + 1] == pages[j] + 1:
            j += 1
        parts.append(str(pages[i] + 1) if i == j else f"{pages[i] + 1}-{pages[j] + 1}")
        i = j + 1
    return ", ".join(parts)


# ------------------------------------------------------------------------- filenames
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def sanitize_filename(name: str, fallback: str = "output") -> str:
    """Make a string safe as a single Windows/POSIX file name component."""
    name = _BAD_CHARS.sub("_", name).strip(" .")
    if not name or name.split(".")[0].upper() in _RESERVED:
        name = f"{fallback}_{name}" if name else fallback
    return name[:150]


def unique_path(path: Path) -> Path:
    """Return ``path`` or ``name (1).ext``, ``name (2).ext`` … if it exists."""
    path = Path(path)
    if not path.exists():
        return path
    for i in range(1, 10_000):
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
    raise OutputError("Could not find a free output file name.")


def same_file(a: Path, b: Path) -> bool:
    try:
        if Path(a).exists() and Path(b).exists():
            return os.path.samefile(a, b)
        return Path(a).resolve() == Path(b).resolve()
    except OSError:
        return False


# ------------------------------------------------------------------------ output I/O
def protected_directories() -> list[Path]:
    dirs: list[Path] = []
    for var in ("WINDIR", "ProgramFiles", "ProgramFiles(x86)"):
        if os.environ.get(var):
            dirs.append(Path(os.environ[var]))
    if sys.platform != "win32":
        dirs += [Path(p) for p in ("/bin", "/sbin", "/usr", "/etc", "/boot", "/lib", "/proc", "/sys")]
    if getattr(sys, "frozen", False):  # packaged app: never write into its own install folder
        dirs.append(Path(sys.executable).resolve().parent)
    return dirs


def friendly_os_error(exc: OSError, target: Path) -> OutputError:
    if isinstance(exc, PermissionError):
        return OutputError(f"Permission denied writing to '{Path(target).parent}'. Choose a folder you can write to.")
    if exc.errno == errno.ENOSPC:
        return OutputError("There is not enough free disk space for the output file.")
    if exc.errno in (errno.ENOENT, errno.ENOTDIR, errno.EINVAL):
        return OutputError(f"'{target}' is not a valid output location.")
    return OutputError(f"Could not write '{Path(target).name}': {exc.strerror or exc}")


def check_output_dir(directory: Path) -> Path:
    """Validate (and create) an output directory. Returns the resolved path."""
    directory = Path(directory)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        resolved = directory.resolve()
    except OSError as exc:
        raise friendly_os_error(exc, directory / "x") from exc
    for bad in protected_directories():
        try:
            resolved.relative_to(bad.resolve())
        except ValueError:
            continue
        raise OutputError(f"Writing into '{bad}' is not allowed. Choose another folder, such as Documents.")
    if not os.access(resolved, os.W_OK):
        raise OutputError(f"'{resolved}' is not writable.")
    return resolved


def check_output_file(path: Path, overwrite: bool) -> Path:
    path = Path(path)
    check_output_dir(path.parent)
    if path.is_dir():
        raise OutputError(f"'{path}' is a folder. Enter a file name.")
    if path.exists() and not overwrite:
        raise OutputExistsError([path])
    return path


def check_no_collisions(paths: Sequence[Path], overwrite: bool) -> None:
    existing = [p for p in paths if Path(p).exists()]
    if existing and not overwrite:
        raise OutputExistsError(existing)


@contextmanager
def atomic_output(final: Path, overwrite: bool = False) -> Iterator[Path]:
    """Yield a temporary path beside ``final``; move it into place only on success.

    The temp file keeps the real suffix (libraries pick the format from it).
    """
    final = check_output_file(final, overwrite)
    tmp = final.with_name(f".{final.stem[:60]}.{uuid.uuid4().hex[:8]}.tmp{final.suffix}")
    try:
        yield tmp
        if not tmp.exists() or tmp.stat().st_size == 0:
            raise ConversionError("The operation finished but produced no output file.")
        os.replace(tmp, final)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise friendly_os_error(exc, final) from exc
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


# --------------------------------------------------------------------- PDF open/check
def is_restricted(doc: pymupdf.Document) -> bool:
    """True if the PDF is encrypted *or* carries permission restrictions."""
    if doc.needs_pass or doc.is_encrypted:
        return True
    perms = doc.permissions
    return perms != -1 and (perms & PAGE_PERM_MASK) != PAGE_PERM_MASK


PROTECTED_HINT = (
    "'{name}' is password-protected or has permission restrictions. "
    "Use 'Unlock PDF' first (you need the password); this tool will not silently remove protection."
)


def load_pdf_raw(path: Path, *, replacing: Optional[Path] = None) -> pymupdf.Document:
    """Validate the file and parse it, with no password handling. Caller must close the document."""
    path = Path(path)
    if not path.is_file():
        raise InvalidInputError(f"File not found: {path.name}")
    if path.stat().st_size == 0:
        raise InvalidInputError(f"'{path.name}' is empty.")
    try:
        with path.open("rb") as fh:
            head = fh.read(1024)
    except OSError as exc:
        raise InvalidInputError(f"Cannot read '{path.name}': {exc.strerror or exc}") from exc
    if b"%PDF-" not in head:
        raise InvalidInputError(f"'{path.name}' is not a PDF file.")
    try:
        if replacing is not None and same_file(path, replacing):
            # output will replace this file: read it into memory so the rename also works on Windows
            return pymupdf.open(stream=path.read_bytes(), filetype="pdf")
        return pymupdf.open(path)
    except Exception as exc:  # PyMuPDF raises several RuntimeError subclasses
        raise InvalidInputError(f"'{path.name}' is damaged or not a valid PDF.") from exc


@contextmanager
def open_pdf(
    path: Path,
    *,
    password: Optional[str] = None,
    allow_protected: bool = False,
    replacing: Optional[Path] = None,
) -> Iterator[pymupdf.Document]:
    """Open and validate a PDF, raising friendly errors.

    ``allow_protected`` - used by PDF->image, which accepts a password to *read* pages.
    ``replacing`` - see :func:`load_pdf_raw`.
    """
    path = Path(path)
    doc = load_pdf_raw(path, replacing=replacing)
    try:
        if doc.needs_pass:
            if not password:
                raise PasswordRequiredError(
                    f"'{path.name}' needs a password to open." if allow_protected
                    else PROTECTED_HINT.format(name=path.name))
            if not doc.authenticate(password):
                raise WrongPasswordError(f"The password for '{path.name}' is incorrect.")
        elif not allow_protected and is_restricted(doc):
            raise InvalidInputError(PROTECTED_HINT.format(name=path.name))
        if doc.page_count == 0:
            raise InvalidInputError(f"'{path.name}' has no pages.")
        yield doc
    finally:
        doc.close()


def structure_warnings(doc: pymupdf.Document, name: str) -> list[str]:
    """Warn about advanced PDF structures that a modifying operation may alter."""
    warns: list[str] = []
    try:
        if doc.is_form_pdf:
            signed = any(
                w.field_type == pymupdf.PDF_WIDGET_TYPE_SIGNATURE for pg in doc for w in (pg.widgets() or [])
            )
            if signed:
                warns.append(f"'{name}' contains digital signatures; they will NOT remain valid after this operation.")
            warns.append(f"'{name}' contains form fields; they may be flattened or altered.")
        if doc.get_toc():
            warns.append(f"'{name}' has bookmarks; they may be changed or lost.")
        if doc.embfile_count():
            warns.append(f"'{name}' has embedded attachments; they may not be carried over.")
    except Exception:  # advisory only – never fail an operation because of a warning check
        log.debug("structure_warnings failed", exc_info=True)
    return warns


def validate_output_pdf(path: Path, expected_pages: Optional[int] = None, password: Optional[str] = None) -> int:
    """Re-open a produced PDF and verify it. Returns the page count."""
    try:
        doc = pymupdf.open(path)
    except Exception as exc:
        raise ConversionError("The output PDF could not be re-opened, so it was not accepted.") from exc
    try:
        if doc.needs_pass and not (password and doc.authenticate(password)):
            raise ConversionError("The output PDF could not be verified with the given password.")
        n = doc.page_count
        if n == 0 or (expected_pages is not None and n != expected_pages):
            raise ConversionError(f"Output check failed: expected {expected_pages} page(s) but found {n}.")
        doc[0].get_text()  # forces the page tree to load
        return n
    finally:
        doc.close()


def copy_metadata(src: pymupdf.Document, dst: pymupdf.Document) -> None:
    try:
        keep = ("title", "author", "subject", "keywords", "creator", "producer")
        meta = {k: v for k, v in (src.metadata or {}).items() if k in keep and v}
        if meta:
            dst.set_metadata({**(dst.metadata or {}), **meta})
    except Exception:
        log.debug("metadata copy failed", exc_info=True)


def save_pdf(doc: pymupdf.Document, tmp: Path, **kw: Any) -> None:
    doc.save(tmp, garbage=kw.pop("garbage", 3), deflate=kw.pop("deflate", True), **kw)


def human_size(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def size_change(before: int, after: int) -> str:
    if before <= 0:
        return human_size(after)
    pct = (before - after) / before * 100
    word = "saved" if pct >= 0 else "larger"
    return f"{human_size(before)} → {human_size(after)} ({abs(pct):.1f}% {word})"


# =========================================================================== LibreOffice engine (Word/PPT/Excel)
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


# =========================================================================== tool definitions (used by main.py)
PDF_EXT = (".pdf",)


@dataclass(frozen=True)
class Option:
    """One option widget in a tool's workspace. kind: choice | int | bool | text | password | sheets"""
    key: str
    label: str
    kind: str
    default: Any = None
    choices: tuple = ()                 # (label, value) pairs for kind == "choice"
    minimum: int = 0
    maximum: int = 100
    special: str = ""                   # text shown for the minimum value of an int (e.g. "No limit")
    suffix: str = ""
    tooltip: str = ""
    placeholder: str = ""
    show_if: Optional[Callable[[dict], bool]] = None


@dataclass
class Request:
    """Everything a tool's run() needs; built by the GUI from the widgets."""
    inputs: list
    output: Path
    options: dict
    overwrite: bool = False
    plan: Optional[list] = None         # Organize PDF: list of PagePlan
    html_text: Optional[str] = None


@dataclass(frozen=True)
class ToolDef:
    """Metadata + options + run() for one tool. Each feature file exposes exactly one: ``TOOL``."""
    id: str
    title: str
    description: str
    category: str
    icon: str
    input_kind: str                     # files | file | html
    extensions: tuple
    run: Callable[[Request, JobContext], Result]
    default_output: Callable[[list, dict], str]
    options: tuple = ()
    min_inputs: int = 1
    reorderable: bool = False
    viewer: str = "none"                # none | select | organize (page thumbnails)
    output_kind: str = "file"           # file | folder
    output_ext: str = ".pdf"
    notice: str = ""
    cancellable: bool = True
    validate: Optional[Callable[[list, dict], Optional[str]]] = None
    confirm: Optional[Callable[[dict], Optional[str]]] = None
    output_disabled_if: Optional[Callable[[dict], bool]] = None
    result_table: Optional[Callable[[Result], tuple]] = None
    search_terms: str = ""


def stem(inputs: list, fallback: str = "document") -> str:
    return sanitize_filename(Path(inputs[0]).stem, fallback) if inputs else fallback
