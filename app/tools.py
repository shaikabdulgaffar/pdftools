"""Registry of the 16 tools.

Each :class:`ToolDef` is pure data plus a ``run`` adapter that calls the real implementation in ``core``.
This module has no Qt imports so it can be unit-tested and reused by the GUI workspace generically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from core import (excel_to_pdf, html_to_pdf, image_compress, image_to_pdf, pdf_compress, pdf_extract_pages,
                  pdf_image_pdf, pdf_merge, pdf_organize, pdf_remove_pages, pdf_security, pdf_split,
                  pdf_to_image, powerpoint_to_pdf, word_to_pdf)
from core.common import JobContext, Result, human_size, load_pdf_raw, sanitize_filename

CATEGORIES = ["PDF Management", "Convert to PDF", "Convert from PDF", "Security", "Image Tools"]
CATEGORY_BLURB = {
    "PDF Management": "Combine, cut, clean up and shrink PDF files.",
    "Convert to PDF": "Turn images, Office documents and web pages into PDF.",
    "Convert from PDF": "Export PDF pages as images, or flatten a PDF into pictures.",
    "Security": "Add or remove password protection (for files you are authorised to change).",
    "Image Tools": "Reduce the file size of photos and graphics.",
}

PDF_EXT = (".pdf",)
IMAGE_EXT = image_to_pdf.SUPPORTED_EXTENSIONS


# ----------------------------------------------------------------------------- model
@dataclass(frozen=True)
class Option:
    key: str
    label: str
    kind: str                                   # choice | int | bool | text | password | sheets
    default: Any = None
    choices: tuple[tuple[str, Any], ...] = ()   # (label, value) for kind == "choice"
    minimum: int = 0
    maximum: int = 100
    special: str = ""                           # text shown for the minimum value of an int (e.g. "No limit")
    suffix: str = ""
    tooltip: str = ""
    placeholder: str = ""
    show_if: Optional[Callable[[dict], bool]] = None


@dataclass
class Request:
    inputs: list[Path]
    output: Path
    options: dict[str, Any]
    overwrite: bool = False
    plan: Optional[list[pdf_organize.PagePlan]] = None
    html_text: Optional[str] = None


@dataclass(frozen=True)
class ToolDef:
    id: str
    title: str
    description: str
    category: str
    icon: str
    input_kind: str                              # files | file | html
    extensions: tuple[str, ...]
    run: Callable[[Request, JobContext], Result]
    default_output: Callable[[list[Path], dict], str]
    options: tuple[Option, ...] = ()
    min_inputs: int = 1
    reorderable: bool = False
    viewer: str = "none"                         # none | select | organize (page thumbnails)
    output_kind: str = "file"                    # file | folder
    output_ext: str = ".pdf"
    notice: str = ""
    cancellable: bool = True
    validate: Optional[Callable[[list[Path], dict], Optional[str]]] = None
    confirm: Optional[Callable[[dict], Optional[str]]] = None
    output_disabled_if: Optional[Callable[[dict], bool]] = None
    result_table: Optional[Callable[[Result], tuple[list[str], list[list[str]]]]] = None
    search_terms: str = ""


# --------------------------------------------------------------------------- helpers
def _stem(inputs: list[Path], fallback: str = "document") -> str:
    return sanitize_filename(inputs[0].stem, fallback) if inputs else fallback


def describe_file(path: Path) -> str:
    """One-line info shown in input lists (page count, dimensions, size)."""
    path = Path(path)
    try:
        size = human_size(path.stat().st_size)
        ext = path.suffix.lower()
        if ext == ".pdf":
            doc = load_pdf_raw(path)
            try:
                if doc.needs_pass:
                    return f"Password-protected · {size}"
                return f"{doc.page_count} page(s) · {size}"
            finally:
                doc.close()
        if ext in IMAGE_EXT:
            info = image_compress.image_info(path)
            return f"{info.width}×{info.height} px · {info.format} · {size}"
        return size
    except Exception as exc:  # advisory display only
        return f"Cannot read file ({str(exc)[:60]})"


def load_sheets(path: Path) -> list[excel_to_pdf.SheetInfo]:
    return excel_to_pdf.list_sheets(path)


def _need_password_match(inputs: list[Path], o: dict) -> Optional[str]:
    if not o.get("password"):
        return "Enter a password to open the PDF."
    if o["password"] != o.get("confirm"):
        return "The two passwords do not match."
    if o.get("owner") and o["owner"] == o["password"]:
        return "Use a different owner password, or leave it empty (an identical one gives no real restrictions)."
    return None


def _images_table(res: Result) -> tuple[list[str], list[list[str]]]:
    rows = []
    for o in res.details.get("outcomes", []):
        rows.append([o.source.name, human_size(o.original_size),
                     human_size(o.new_size) if not o.skipped else "unchanged",
                     f"{o.percent_saved:.1f}%" if not o.skipped else "–",
                     f"{o.original_dims[0]}×{o.original_dims[1]}" + (
                         f" → {o.new_dims[0]}×{o.new_dims[1]}" if o.new_dims != o.original_dims else "")])
    return ["File", "Original", "New", "Saved", "Dimensions"], rows


# ---------------------------------------------------------------------- run adapters
def _run_merge(r: Request, ctx: JobContext) -> Result:
    return pdf_merge.merge_pdfs(r.inputs, r.output, overwrite=r.overwrite, ctx=ctx)


def _run_split(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return pdf_split.split_pdf(r.inputs[0], r.output, mode=o["mode"], ranges_spec=o.get("ranges", ""),
                               every_n=o.get("every_n", 1), overwrite=r.overwrite, ctx=ctx)


def _run_remove(r: Request, ctx: JobContext) -> Result:
    return pdf_remove_pages.remove_pages(r.inputs[0], r.output, r.options["pages"], overwrite=r.overwrite, ctx=ctx)


def _run_extract(r: Request, ctx: JobContext) -> Result:
    return pdf_extract_pages.extract_pages(r.inputs[0], r.output, r.options["pages"],
                                           custom_order=r.options.get("custom_order", False),
                                           overwrite=r.overwrite, ctx=ctx)


def _run_organize(r: Request, ctx: JobContext) -> Result:
    return pdf_organize.organize_pdf(r.inputs[0], r.output, r.plan or [], overwrite=r.overwrite, ctx=ctx)


def _run_compress(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return pdf_compress.compress_pdf(r.inputs[0], r.output, o["preset"], image_dpi=o.get("image_dpi") or None,
                                     image_quality=o.get("image_quality") or None, overwrite=r.overwrite, ctx=ctx)


def _run_img2pdf(r: Request, ctx: JobContext) -> Result:
    o = r.options
    opt = image_to_pdf.LayoutOptions(page_size=o["page_size"], orientation=o["orientation"],
                                     margin_mm=float(o["margin"]), placement=o["placement"], alignment=o["alignment"])
    return image_to_pdf.images_to_pdf(r.inputs, r.output, opt, overwrite=r.overwrite, ctx=ctx)


def _run_word(r: Request, ctx: JobContext) -> Result:
    return word_to_pdf.word_to_pdf(r.inputs[0], r.output, overwrite=r.overwrite, ctx=ctx)


def _run_ppt(r: Request, ctx: JobContext) -> Result:
    return powerpoint_to_pdf.powerpoint_to_pdf(r.inputs[0], r.output, overwrite=r.overwrite, ctx=ctx)


def _run_excel(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return excel_to_pdf.excel_to_pdf(r.inputs[0], r.output, sheets=o.get("sheets") or None,
                                     orientation=o.get("orientation", "keep"), fit_to_width=o.get("fit", False),
                                     overwrite=r.overwrite, ctx=ctx)


def _run_html(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return html_to_pdf.html_to_pdf(r.output, html_file=r.inputs[0] if r.inputs else None, html_text=r.html_text,
                                   page_size=o["page_size"], orientation=o["orientation"],
                                   margin_mm=float(o["margin"]), overwrite=r.overwrite, ctx=ctx)


def _run_pdf2img(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return pdf_to_image.pdf_to_images(r.inputs[0], r.output, fmt=o["format"], dpi=int(o["dpi"]),
                                      jpeg_quality=int(o["quality"]), pages_spec=o.get("pages", ""),
                                      password=o.get("password") or None, overwrite=r.overwrite, ctx=ctx)


def _run_protect(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return pdf_security.protect_pdf(r.inputs[0], r.output, o["password"], o.get("owner") or None,
                                    allow_print=o["allow_print"], allow_copy=o["allow_copy"],
                                    allow_modify=o["allow_modify"], allow_annotate=o["allow_annotate"],
                                    overwrite=r.overwrite, ctx=ctx)


def _run_unlock(r: Request, ctx: JobContext) -> Result:
    return pdf_security.unlock_pdf(r.inputs[0], r.output, r.options.get("password", ""), overwrite=r.overwrite, ctx=ctx)


def _run_rasterize(r: Request, ctx: JobContext) -> Result:
    o = r.options
    return pdf_image_pdf.pdf_to_image_to_pdf(r.inputs[0], r.output, dpi=int(o["dpi"]), fmt=o["format"],
                                             jpeg_quality=int(o["quality"]), overwrite=r.overwrite, ctx=ctx)


def _run_imgcompress(r: Request, ctx: JobContext) -> Result:
    o = r.options
    opt = image_compress.CompressOptions(
        quality=int(o["quality"]), max_width=int(o["max_width"]) or None, max_height=int(o["max_height"]) or None,
        out_format=o["out_format"], png_reduce_colors=o["png_reduce"], overwrite_originals=o["overwrite"])
    return image_compress.compress_images(r.inputs, None if o["overwrite"] else r.output, opt, ctx=ctx)


# ----------------------------------------------------------------- shared option sets
_DPI_CHOICES = tuple((k, v) for k, v in pdf_to_image.DPI_PRESETS.items())
_PAGE_SIZE = Option("page_size", "Page size", "choice", "a4", (("A4", "a4"), ("US Letter", "letter")))
_ORIENT = Option("orientation", "Orientation", "choice", "portrait", (("Portrait", "portrait"), ("Landscape", "landscape")))
_PAGES_TXT = Option("pages", "Pages", "text", "", placeholder="e.g. 1-3, 5, 8-10",
                    tooltip="Page numbers and ranges separated by commas. Selecting thumbnails fills this in.")

TOOLS: list[ToolDef] = [
    # ---------------------------------------------------------------- PDF Management
    ToolDef("merge", "Merge PDF", "Combine several PDFs into one, in the order shown.", "PDF Management", "merge",
            "files", PDF_EXT, _run_merge, lambda i, o: "merged.pdf", min_inputs=2, reorderable=True,
            search_terms="combine join concatenate"),
    ToolDef("split", "Split PDF", "Cut a PDF into single pages, page ranges, or chunks of N pages.",
            "PDF Management", "split", "file", PDF_EXT, _run_split, lambda i, o: f"{_stem(i)}_split",
            options=(Option("mode", "Split mode", "choice", "pages",
                            (("Every page as its own file", "pages"), ("Custom page ranges", "ranges"),
                             ("Every N pages", "every"))),
                     Option("ranges", "Ranges", "text", "", placeholder="e.g. 1-3, 5, 8-10",
                            show_if=lambda o: o.get("mode") == "ranges",
                            tooltip="Each range becomes its own PDF."),
                     Option("every_n", "Pages per file", "int", 5, minimum=1, maximum=10000,
                            show_if=lambda o: o.get("mode") == "every")),
            output_kind="folder", search_terms="separate divide cut"),
    ToolDef("remove", "Remove Pages", "Delete unwanted pages and save a new PDF.", "PDF Management", "remove",
            "file", PDF_EXT, _run_remove, lambda i, o: f"{_stem(i)}_removed.pdf", options=(_PAGES_TXT,),
            viewer="select", search_terms="delete pages"),
    ToolDef("extract", "Extract Pages", "Copy selected pages into a new PDF.", "PDF Management", "extract",
            "file", PDF_EXT, _run_extract, lambda i, o: f"{_stem(i)}_extracted.pdf",
            options=(_PAGES_TXT, Option("custom_order", "Use the order I typed (allows repeats)", "bool", False)),
            viewer="select", search_terms="pick select pages"),
    ToolDef("organize", "Organize PDF", "Reorder, rotate, duplicate and delete pages visually.", "PDF Management",
            "organize", "file", PDF_EXT, _run_organize, lambda i, o: f"{_stem(i)}_organized.pdf",
            viewer="organize", notice="Bookmarks are not kept when pages are rearranged. Digital signatures become invalid.",
            search_terms="rearrange reorder rotate sort"),
    ToolDef("compress", "Compress PDF", "Reduce file size. Text and vector graphics stay sharp.", "PDF Management",
            "compress", "file", PDF_EXT, _run_compress, lambda i, o: f"{_stem(i)}_compressed.pdf",
            options=(Option("preset", "Compression level", "choice", "medium",
                            tuple((p.label, k) for k, p in pdf_compress.PRESETS.items()),
                            tooltip="\n".join(f"{p.label}: {p.explanation}" for p in pdf_compress.PRESETS.values())),
                     Option("image_dpi", "Image resolution override", "int", 0, minimum=0, maximum=600, special="Use preset",
                            suffix=" dpi", tooltip="Optional. Images sharper than this are down-sampled."),
                     Option("image_quality", "Image quality override", "int", 0, minimum=0, maximum=95, special="Use preset",
                            tooltip="Optional. JPEG quality for re-encoded images (higher = larger, sharper).")),
            notice="Smaller files cost image quality: Low is lossless, Medium is balanced, High visibly softens photos. "
                   "Some PDFs cannot shrink — the result tells you what really happened.",
            cancellable=False, search_terms="reduce size shrink smaller optimize"),
    # ---------------------------------------------------------------- Convert to PDF
    ToolDef("img2pdf", "Image to PDF", "Turn JPG, PNG, BMP, TIFF and WebP images into a PDF.", "Convert to PDF", "image",
            "files", IMAGE_EXT, _run_img2pdf, lambda i, o: f"{_stem(i, 'images')}.pdf", reorderable=True,
            options=(Option("page_size", "Page size", "choice", "a4",
                            (("A4", "a4"), ("US Letter", "letter"), ("Same as image", "image"))),
                     Option("orientation", "Orientation", "choice", "auto",
                            (("Automatic", "auto"), ("Portrait", "portrait"), ("Landscape", "landscape")),
                            show_if=lambda o: o.get("page_size") != "image"),
                     Option("placement", "Image size", "choice", "fit",
                            (("Fit to page", "fit"), ("Original size (shrink if too big)", "actual"))),
                     Option("alignment", "Position", "choice", "center", (("Centered", "center"), ("Top", "top"))),
                     Option("margin", "Margin", "int", 10, minimum=0, maximum=60, suffix=" mm")),
            notice="JPEG files are embedded without re-encoding. Multipage TIFFs create one page per frame.",
            search_terms="jpg png photo picture"),
    ToolDef("word2pdf", "Word to PDF", "Convert Word documents to PDF with the LibreOffice engine.", "Convert to PDF",
            "word", "file", word_to_pdf.SUPPORTED, _run_word, lambda i, o: f"{_stem(i)}.pdf",
            notice="Requires LibreOffice (free). Layout is rendered by LibreOffice, so fonts and spacing can differ "
                   "slightly from Microsoft Word.", search_terms="docx doc office"),
    ToolDef("ppt2pdf", "PowerPoint to PDF", "One PDF page per slide, rendered by LibreOffice.", "Convert to PDF", "ppt",
            "file", powerpoint_to_pdf.SUPPORTED, _run_ppt, lambda i, o: f"{_stem(i)}.pdf",
            notice="Requires LibreOffice (free). Animations and transitions do not exist in PDF.",
            search_terms="pptx slides presentation deck"),
    ToolDef("xls2pdf", "Excel to PDF", "Export workbooks (all or selected sheets) to PDF.", "Convert to PDF", "excel",
            "file", excel_to_pdf.SUPPORTED, _run_excel, lambda i, o: f"{_stem(i)}.pdf",
            options=(Option("sheets", "Sheets to export", "sheets", None,
                            tooltip="Only for .xlsx. Leave all ticked to export everything."),
                     Option("orientation", "Page orientation", "choice", "keep",
                            (("Use the workbook's setting", "keep"), ("Portrait", "portrait"), ("Landscape", "landscape"))),
                     Option("fit", "Fit each sheet to one page wide", "bool", False)),
            notice="Requires LibreOffice (free). Print areas and scaling in the workbook are respected unless you "
                   "override them below. Overrides re-save the workbook, which can drop charts.",
            search_terms="xlsx spreadsheet workbook"),
    ToolDef("html2pdf", "HTML to PDF", "Convert a local HTML file, or HTML you paste, into a PDF.", "Convert to PDF", "html",
            "html", (".html", ".htm", ".xhtml"), _run_html, lambda i, o: f"{_stem(i, 'webpage')}.pdf",
            options=(_PAGE_SIZE, _ORIENT, Option("margin", "Margin", "int", 15, minimum=0, maximum=60, suffix=" mm")),
            notice="Works offline. Supports common HTML and a subset of CSS; JavaScript, web fonts and online "
                   "resources are not available.", search_terms="web page website"),
    # -------------------------------------------------------------- Convert from PDF
    ToolDef("pdf2img", "PDF to Image", "Export pages as PNG or JPEG pictures.", "Convert from PDF", "pdf2img",
            "file", PDF_EXT, _run_pdf2img, lambda i, o: f"{_stem(i)}_images",
            options=(Option("format", "Format", "choice", "png", (("PNG (lossless)", "png"), ("JPEG (smaller)", "jpeg"))),
                     Option("dpi", "Resolution", "choice", 150, _DPI_CHOICES),
                     Option("quality", "JPEG quality", "int", 90, minimum=10, maximum=100,
                            show_if=lambda o: o.get("format") == "jpeg"),
                     Option("pages", "Pages", "text", "", placeholder="All pages — or e.g. 1-3, 5"),
                     Option("password", "Password", "password", "", placeholder="Only if the PDF is protected")),
            output_kind="folder", search_terms="png jpg export render"),
    ToolDef("rasterize", "PDF to Image to PDF", "Flatten a PDF: every page becomes a picture inside a new PDF.",
            "Convert from PDF", "raster", "file", PDF_EXT, _run_rasterize,
            lambda i, o: f"{_stem(i)}_rasterized.pdf",
            options=(Option("dpi", "Resolution", "choice", 150, _DPI_CHOICES),
                     Option("format", "Image type", "choice", "jpeg", (("JPEG (smaller)", "jpeg"), ("PNG (lossless)", "png"))),
                     Option("quality", "JPEG quality", "int", 80, minimum=10, maximum=100,
                            show_if=lambda o: o.get("format") == "jpeg")),
            notice="Rasterization warning: text becomes a picture. Selectable and searchable text, links, forms, "
                   "bookmarks and vector graphics are lost, and the file may get larger. Useful for flattening "
                   "scans or removing hidden layers.", search_terms="flatten scan print"),
    # -------------------------------------------------------------------- Security
    ToolDef("protect", "Protect PDF", "Encrypt a PDF with AES-256 and set permissions.", "Security", "lock",
            "file", PDF_EXT, _run_protect, lambda i, o: f"{_stem(i)}_protected.pdf",
            options=(Option("password", "Open password", "password", "", placeholder="Required to open the file"),
                     Option("confirm", "Confirm password", "password", ""),
                     Option("owner", "Owner password (optional)", "password", "",
                            placeholder="Needed to change the permissions",
                            tooltip="Use a different password from the open password, or restrictions are meaningless."),
                     Option("allow_print", "Allow printing", "bool", True),
                     Option("allow_copy", "Allow copying text", "bool", True),
                     Option("allow_modify", "Allow editing", "bool", True),
                     Option("allow_annotate", "Allow comments & annotations", "bool", True)),
            notice="Permissions are a courtesy honoured by compliant software; they do not prevent screenshots or "
                   "determined copying. Only the open password keeps content private. If you forget it, the file "
                   "cannot be recovered.", validate=_need_password_match, search_terms="encrypt password secure"),
    ToolDef("unlock", "Unlock PDF", "Remove protection from a PDF — you must know its password.", "Security", "unlock",
            "file", PDF_EXT, _run_unlock, lambda i, o: f"{_stem(i)}_unlocked.pdf",
            options=(Option("password", "Password", "password", "", placeholder="The PDF's password"),),
            notice="For files you are authorised to modify. This tool cannot recover or guess forgotten passwords.",
            validate=lambda i, o: None if o.get("password") else "Enter the PDF's password.",
            search_terms="decrypt remove password"),
    # ------------------------------------------------------------------ Image Tools
    ToolDef("imgcompress", "Image Compressor", "Shrink JPEG, PNG, WebP, BMP and TIFF images in batches.",
            "Image Tools", "compress_img", "files", image_compress.SUPPORTED_EXTENSIONS, _run_imgcompress,
            lambda i, o: "compressed_images" if not i else f"{i[0].parent.name or 'images'}_compressed",
            options=(Option("quality", "Quality (JPEG / WebP)", "int", 80, minimum=1, maximum=100,
                            tooltip="Lower = smaller file. 70–85 is a good range for photos."),
                     Option("max_width", "Maximum width", "int", 0, minimum=0, maximum=20000, special="No limit", suffix=" px"),
                     Option("max_height", "Maximum height", "int", 0, minimum=0, maximum=20000, special="No limit", suffix=" px"),
                     Option("out_format", "Output format", "choice", "same",
                            (("Keep original format", "same"), ("JPEG (photos)", "jpeg"), ("PNG (graphics)", "png"),
                             ("WebP (smallest)", "webp"))),
                     Option("png_reduce", "Reduce PNG colours (graphics only)", "bool", False,
                            tooltip="Lossy 256-colour palette. Great for logos and charts, poor for photos."),
                     Option("overwrite", "Replace the original files", "bool", False,
                            tooltip="Only replaces a file when the result is smaller.")),
            output_kind="folder", output_ext="", cancellable=True,
            output_disabled_if=lambda o: bool(o.get("overwrite")),
            confirm=lambda o: ("This will overwrite your original image files with the compressed versions. "
                               "This cannot be undone. Continue?") if o.get("overwrite") else None,
            result_table=_images_table, notice="Originals are never changed unless you tick 'Replace the original files'. "
                                               "Photo metadata such as GPS location is removed from compressed copies.",
            search_terms="photo reduce size jpg png webp"),
]

TOOLS_BY_ID = {t.id: t for t in TOOLS}
assert len(TOOLS) == 16 and len(TOOLS_BY_ID) == 16
