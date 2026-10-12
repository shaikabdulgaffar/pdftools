"""PDF Toolkit - main file: GUI + the list of tools.

Run:  python main.py          (self-check without GUI:  python main.py --selftest)

Project layout (one flat folder):
  main.py        this file - window, pages, generic tool workspace, TOOLS list
  utils.py       shared helpers (errors, safe output writing, LibreOffice helper, Option/ToolDef dataclasses)
  <feature>.py   one file per tool: its processing code + its TOOL definition (the options shown in the GUI)
"""
from __future__ import annotations

import logging
import os
import sys
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from string import Template
from typing import Any, Callable, Optional, Sequence

import PIL
import pymupdf
from PIL import Image
from PySide6.QtCore import QByteArray, QSettings, QSize, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFileDialog, QFormLayout, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel,
                               QLineEdit, QListView, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
                               QPlainTextEdit, QProgressBar, QPushButton, QRadioButton, QScrollArea, QSpinBox,
                               QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

# Feature files live in sub-folders next to this file. Add the folders to the import path so that
# `import merge_pdf` etc. work wherever the files are moved. (utils.py stays beside main.py.)
_ROOT = Path(__file__).resolve().parent
for _folder in ("pdf_management", "convert_to_pdf", "convert_from_pdf", "security", "image_tools"):
    if (_ROOT / _folder).is_dir():
        sys.path.insert(0, str(_ROOT / _folder))

import compress_pdf
import excel_to_pdf
import extract_pages
import html_to_pdf
import image_compress
import image_to_pdf
import merge_pdf
import organize_pdf
import pdf_to_image
import pdf_to_image_to_pdf
import powerpoint_to_pdf
import protect_pdf
import remove_pages
import split_pdf
import unlock_pdf
import word_to_pdf
from organize_pdf import PagePlan
from utils import (JobContext, OperationCancelled, Option, OutputExistsError, Request, Result,
                   ToolDef, ToolkitError, find_soffice, human_size, load_pdf_raw, open_pdf, pages_to_spec,
                   sanitize_filename)

log = logging.getLogger("pdf_toolkit")
ROLE = Qt.UserRole


# ====================================================================================================
# Settings (non-sensitive preferences only)
# ====================================================================================================

class AppSettings:
    def __init__(self) -> None:
        self._s = QSettings("PDFToolkit", "PDFToolkit")

    @property
    def theme(self) -> str:
        return "dark" if self._s.value("theme", "light") == "dark" else "light"

    @theme.setter
    def theme(self, value: str) -> None:
        self._s.setValue("theme", value)

    @property
    def default_output_dir(self) -> str:
        return str(self._s.value("default_output_dir", "") or "")

    @default_output_dir.setter
    def default_output_dir(self, value: str) -> None:
        self._s.setValue("default_output_dir", value)

    @property
    def last_output_dir(self) -> str:
        return str(self._s.value("last_output_dir", "") or "")

    @last_output_dir.setter
    def last_output_dir(self, value: str) -> None:
        self._s.setValue("last_output_dir", value)

    @property
    def recent_tools(self) -> list[str]:
        v = self._s.value("recent_tools", [])
        return [v] if isinstance(v, str) else list(v or [])

    def push_recent(self, tool_id: str, limit: int = 4) -> None:
        items = [t for t in self.recent_tools if t != tool_id]
        self._s.setValue("recent_tools", [tool_id, *items][:limit])

# ====================================================================================================
# Theme
# ====================================================================================================

PALETTES = {
    "light": dict(bg="#F4F6FA", surface="#FFFFFF", border="#E2E8F0", text="#0F1B33", muted="#5B6B82",
                  accent="#2563EB", accent_hover="#1D4ED8", accent_soft="#E8F0FE", hover="#F1F5F9",
                  danger="#B42318", danger_soft="#FEF3F2", warn="#8A5300", warn_soft="#FFF6E5",
                  ok="#067647", ok_soft="#ECFDF3", input_bg="#FFFFFF", disabled="#CBD5E1"),
    "dark": dict(bg="#0E1525", surface="#16203A", border="#27324D", text="#E6EBF5", muted="#98A6BF",
                 accent="#5B8DEF", accent_hover="#7BA3F5", accent_soft="#1E2D52", hover="#1C2745",
                 danger="#FDA29B", danger_soft="#3A1B1B", warn="#FEC84B", warn_soft="#3A2D12",
                 ok="#75E0A7", ok_soft="#10301F", input_bg="#101A30", disabled="#3B4764"),
}

_QSS = Template("""
* { font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif; font-size: 10pt; color: $text; }
QMainWindow, QStackedWidget, #Page, QScrollArea, #ScrollBody { background: $bg; border: none; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 6px; }
QLabel { background: transparent; }
QLabel#H1 { font-size: 20pt; font-weight: 600; }
QLabel#H2 { font-size: 12pt; font-weight: 600; }
QLabel#Sub, QLabel#Muted { color: $muted; }
QLabel#Notice { background: $warn_soft; color: $warn; border: 1px solid $warn_soft; border-radius: 8px; padding: 10px 12px; }
QLabel#Info { background: $accent_soft; color: $text; border-radius: 8px; padding: 10px 12px; }

#Sidebar { background: $surface; border-right: 1px solid $border; }
#Sidebar QLabel#AppName { font-size: 12pt; font-weight: 700; }
QPushButton#Nav { text-align: left; padding: 9px 12px; border: none; border-radius: 8px; background: transparent; color: $muted; }
QPushButton#Nav:hover { background: $hover; color: $text; }
QPushButton#Nav:checked { background: $accent_soft; color: $accent; font-weight: 600; }

QFrame#Card, QFrame#ToolCard, QFrame#Panel { background: $surface; border: 1px solid $border; border-radius: 12px; }
QFrame#ToolCard:hover, QFrame#ToolCard:focus { border: 1px solid $accent; }
QFrame#ToolCard QLabel { background: transparent; }
QFrame#ToolCard QLabel#CardIcon, QLabel#CardIcon { background: $accent_soft; border-radius: 10px; }
QFrame#DropZone { border: 1.5px dashed $border; border-radius: 10px; background: $bg; }
QFrame#DropZone[active="true"] { border-color: $accent; background: $accent_soft; }
QFrame#Divider { background: $border; max-height: 1px; border: none; }

QPushButton { padding: 8px 16px; border-radius: 8px; border: 1px solid $border; background: $surface; }
QPushButton:hover { background: $hover; }
QPushButton:disabled { color: $disabled; background: $bg; }
QPushButton[variant="primary"] { background: $accent; color: white; border: 1px solid $accent; font-weight: 600; padding: 9px 22px; }
QPushButton[variant="primary"]:hover { background: $accent_hover; border-color: $accent_hover; }
QPushButton[variant="primary"]:disabled { background: $disabled; border-color: $disabled; color: white; }
QPushButton[variant="ghost"] { border: none; background: transparent; color: $accent; padding: 6px 8px; }
QPushButton[variant="ghost"]:hover { background: $accent_soft; }
QPushButton[variant="small"] { padding: 5px 10px; }

QLineEdit, QPlainTextEdit, QSpinBox, QComboBox { background: $input_bg; border: 1px solid $border; border-radius: 8px; padding: 6px 8px; selection-background-color: $accent; selection-color: white; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus { border: 1px solid $accent; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox QAbstractItemView { background: $surface; border: 1px solid $border; selection-background-color: $accent_soft; selection-color: $text; }
QSpinBox::up-button, QSpinBox::down-button { width: 16px; border: none; background: transparent; }

QListWidget, QTableWidget { background: $surface; border: 1px solid $border; border-radius: 10px; outline: none; alternate-background-color: $surface; gridline-color: $border; }
QListWidget::item { padding: 8px; border-radius: 6px; }
QListWidget::item:selected { background: $accent_soft; color: $text; }
QListWidget::item:hover { background: $hover; }
QHeaderView::section { background: $bg; border: none; border-bottom: 1px solid $border; padding: 6px; font-weight: 600; }
QCheckBox { spacing: 8px; background: transparent; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1.5px solid $muted; border-radius: 4px; background: $input_bg; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; }
QRadioButton { background: transparent; }
QProgressBar { background: $border; border: none; border-radius: 4px; max-height: 8px; min-height: 8px; text-align: center; }
QProgressBar::chunk { background: $accent; border-radius: 4px; }
QScrollBar:vertical { background: transparent; width: 12px; margin: 2px; }
QScrollBar::handle:vertical { background: $border; border-radius: 4px; min-height: 30px; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 2px; }
QScrollBar::handle:horizontal { background: $border; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QDialog, QMessageBox { background: $surface; }
""")


def stylesheet(theme: str) -> str:
    return _QSS.substitute(PALETTES["dark" if theme == "dark" else "light"])


def palette(theme: str) -> dict[str, str]:
    return PALETTES["dark" if theme == "dark" else "light"]

# ====================================================================================================
# Icons (original inline SVG)
# ====================================================================================================

_DOC = '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>'
_PATHS: dict[str, str] = {
    "home": '<path d="M4 11 12 4l8 7"/><path d="M6 10v10h12V10"/><path d="M10 20v-5h4v5"/>',
    "merge": '<path d="M12 3 3 8l9 5 9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 16 9 5 9-5"/>',
    "split": '<path d="M12 3v8"/><path d="m12 11-6 7"/><path d="m12 11 6 7"/><path d="M4 18h4M16 18h4"/>',
    "remove": _DOC + '<path d="M9.5 14h5"/>',
    "extract": _DOC + '<path d="M12 18v-6"/><path d="m9.5 14.5 2.5-2.5 2.5 2.5"/>',
    "organize": '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/>'
                '<rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    "compress": '<path d="m4 4 6 6"/><path d="M10 5v5H5"/><path d="m20 20-6-6"/><path d="M14 19v-5h5"/>',
    "compress_img": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m4 18 5-5 3 3 3-3 5 5"/>'
                    '<path d="m14 7 2 2M18 7l-2 2"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
    "word": _DOC + '<path d="m8.5 12 1.5 6 2-5.5 2 5.5 1.5-6"/>',
    "ppt": _DOC + '<path d="M9.5 18v-6h3a2 2 0 0 1 0 4h-3"/>',
    "excel": _DOC + '<path d="m9.5 12 5 6M14.5 12l-5 6"/>',
    "html": '<path d="m8 8-5 4 5 4"/><path d="m16 8 5 4-5 4"/><path d="m13.5 5-3 14"/>',
    "pdf2img": _DOC + '<path d="m8.5 18 2.5-3 2 2 1.5-1.5 1.5 2.5"/>',
    "raster": '<path d="M4 12a8 8 0 0 1 14-5"/><path d="M18 3v4h-4"/><path d="M20 12a8 8 0 0 1-14 5"/><path d="M6 21v-4h4"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "unlock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
    "settings": '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.01"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
    "back": '<path d="m15 5-7 7 7 7"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "up": '<path d="m6 15 6-6 6 6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "left": '<path d="m15 6-6 6 6 6"/>',
    "right": '<path d="m9 6 6 6-6 6"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="m6 7 1 13h10l1-13"/>',
    "rotate_cw": '<path d="M19 12a7 7 0 1 1-2.5-5.4"/><path d="M19 4v4h-4"/>',
    "rotate_ccw": '<path d="M5 12a7 7 0 1 0 2.5-5.4"/><path d="M5 4v4h4"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "alert": '<path d="M12 4 2.5 20h19z"/><path d="M12 10v5"/><path d="M12 17.5v.01"/>',
    "x": '<path d="m6 6 12 12M18 6 6 18"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "play": '<path d="m8 5 11 7-11 7z"/>',
}

_cache: dict[tuple, QIcon] = {}


def _render(name: str, color: str, px: int) -> QPixmap:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>')
    scale = 2  # crisp on high-DPI screens
    pm = QPixmap(px * scale, px * scale)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


def make_icon(name: str, color: str = "#64748B", size: int = 24, checked_color: str | None = None) -> QIcon:
    key = (name, color, size, checked_color)
    if key not in _cache:
        ic = QIcon()
        ic.addPixmap(_render(name, color, size), QIcon.Normal, QIcon.Off)
        ic.addPixmap(_render(name, color, size), QIcon.Disabled, QIcon.Off)
        ic.addPixmap(_render(name, checked_color or color, size), QIcon.Normal, QIcon.On)
        _cache[key] = ic
    return _cache[key]


def logo_pixmap(px: int = 64) -> QPixmap:
    """App logo: blue rounded square with a white page."""
    scale = 2
    pm = QPixmap(px * scale, px * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(Qt.GlobalColor.transparent)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="15" '
           f'fill="#2563EB"/><path d="M20 12h17l9 9v31H20z" fill="#fff"/><path d="M37 12v9h9" fill="#C7D7FB"/>'
           f'<rect x="26" y="34" width="14" height="3" rx="1.5" fill="#2563EB"/>'
           f'<rect x="26" y="41" width="10" height="3" rx="1.5" fill="#93B4F8"/></svg>')
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm

# ====================================================================================================
# Background worker
# ====================================================================================================

log = logging.getLogger("pdf_toolkit")


class JobThread(QThread):
    progress = Signal(int, int, str)        # done, total (0 = unknown), message
    succeeded = Signal(object)              # Result
    failed = Signal(object, str)            # exception, traceback text ("" when expected/cancelled)

    def __init__(self, fn: Callable[[JobContext], Result], parent: Any = None) -> None:
        super().__init__(parent)
        self._fn = fn
        self.ctx = JobContext(progress=self.progress.emit)

    def cancel(self) -> None:
        self.ctx.cancel.cancel()

    def run(self) -> None:  # executes in the worker thread
        try:
            self.succeeded.emit(self._fn(self.ctx))
        except OperationCancelled as exc:
            self.failed.emit(exc, "")
        except Exception as exc:  # noqa: BLE001 - last line of defence: the GUI must never crash
            tb = "" if isinstance(exc, ToolkitError) else traceback.format_exc()
            if tb:
                log.error("Unexpected %s in worker\n%s", type(exc).__name__, tb)  # no document content / passwords
            self.failed.emit(exc, tb)

# ====================================================================================================
# Dialogs
# ====================================================================================================

def confirm(parent: QWidget, title: str, text: str, yes: str = "Continue") -> bool:
    box = QMessageBox(QMessageBox.Warning, title, text, QMessageBox.NoButton, parent)
    ok = box.addButton(yes, QMessageBox.AcceptRole)
    box.addButton("Cancel", QMessageBox.RejectRole)
    box.exec()
    return box.clickedButton() is ok


def confirm_overwrite(parent: QWidget, paths: Sequence[Path]) -> bool:
    names = "\n".join(f"• {p.name}" for p in list(paths)[:6]) + ("\n• …" if len(paths) > 6 else "")
    return confirm(parent, "Replace existing file?",
                   f"These files already exist in '{Path(paths[0]).parent}':\n\n{names}\n\nReplace them?", "Replace")


class ErrorDetailsDialog(QDialog):
    def __init__(self, parent: QWidget, summary: str, details: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Error details")
        self.resize(640, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(summary, wordWrap=True))
        box = QPlainTextEdit(details)
        box.setReadOnly(True)
        lay.addWidget(box, 1)
        btns = QDialogButtonBox()
        copy = QPushButton("Copy to clipboard")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(details))
        btns.addButton(copy, QDialogButtonBox.ActionRole)
        btns.addButton(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

# ====================================================================================================
# Reusable widgets
# ====================================================================================================

def set_variant(btn: QPushButton, variant: str) -> QPushButton:
    btn.setProperty("variant", variant)
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    return btn


def button(text: str, variant: str = "", icon_name: str = "", icon_color: str = "#64748B") -> QPushButton:
    b = QPushButton(text)
    if icon_name:
        b.setIcon(make_icon(icon_name, icon_color, 18))
        b.setIconSize(QSize(18, 18))
    if variant:
        set_variant(b, variant)
    b.setCursor(Qt.PointingHandCursor)
    return b


def urls_to_paths(mime) -> list[Path]:
    return [Path(u.toLocalFile()) for u in mime.urls() if u.isLocalFile()]


class DropListWidget(QListWidget):
    """List that accepts dropped files (external) and optional internal reordering."""

    filesDropped = Signal(list)

    def __init__(self, reorderable: bool) -> None:
        super().__init__()
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAcceptDrops(True)
        self.setIconSize(QSize(20, 20))
        self.setSpacing(2)
        if reorderable:
            self.setDragDropMode(QAbstractItemView.InternalMove)
            self.setDefaultDropAction(Qt.MoveAction)

    def dragEnterEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            self.filesDropped.emit(urls_to_paths(e.mimeData()))
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class Banner(QLabel):
    """Coloured message strip. kind: notice | info"""

    def __init__(self, text: str = "", kind: str = "Notice") -> None:
        super().__init__(text)
        self.setObjectName(kind)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setVisible(bool(text))


def card(object_name: str = "Card") -> QFrame:
    f = QFrame()
    f.setObjectName(object_name)
    return f


class ToolCard(QFrame):
    """Clickable card used on the home and category pages."""

    clicked = Signal(str)

    def __init__(self, tool_id: str, title: str, description: str, icon_name: str, accent: str) -> None:
        super().__init__()
        self.tool_id = tool_id
        self.setObjectName("ToolCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(104)
        self.setAccessibleName(f"{title}. {description}")
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 14, 16, 14)
        row.setSpacing(14)
        ic = QLabel()
        ic.setObjectName("CardIcon")
        ic.setFixedSize(46, 46)
        ic.setAlignment(Qt.AlignCenter)
        ic.setPixmap(make_icon(icon_name, accent, 26).pixmap(26, 26))
        row.addWidget(ic, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setObjectName("H2")
        d = QLabel(description)
        d.setObjectName("Muted")
        d.setWordWrap(True)
        col.addWidget(t)
        col.addWidget(d)
        col.addStretch(1)
        row.addLayout(col, 1)

    def mouseReleaseEvent(self, e) -> None:
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.tool_id)

    def keyPressEvent(self, e) -> None:
        if e.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit(self.tool_id)
        else:
            super().keyPressEvent(e)

# ====================================================================================================
# Tool registry (each tool lives in its own file)
# ====================================================================================================


CATEGORIES = ["PDF Management", "Convert to PDF", "Convert from PDF", "Security", "Image Tools"]
CATEGORY_BLURB = {
    "PDF Management": "Combine, cut, clean up and shrink PDF files.",
    "Convert to PDF": "Turn images, Office documents and web pages into PDF.",
    "Convert from PDF": "Export PDF pages as images, or flatten a PDF into pictures.",
    "Security": "Add or remove password protection (for files you are authorised to change).",
    "Image Tools": "Reduce the file size of photos and graphics.",
}

# One feature file = one tool. To add/remove/reorder a tool, edit this list only.
TOOLS: list[ToolDef] = [
    merge_pdf.TOOL, split_pdf.TOOL, remove_pages.TOOL, extract_pages.TOOL, organize_pdf.TOOL, compress_pdf.TOOL,
    image_to_pdf.TOOL, word_to_pdf.TOOL, powerpoint_to_pdf.TOOL, excel_to_pdf.TOOL, html_to_pdf.TOOL,
    pdf_to_image.TOOL, pdf_to_image_to_pdf.TOOL,
    protect_pdf.TOOL, unlock_pdf.TOOL,
    image_compress.TOOL,
]
TOOLS_BY_ID = {t.id: t for t in TOOLS}
assert len(TOOLS) == 16 and len(TOOLS_BY_ID) == 16


def describe_file(path: Path) -> str:
    """One-line info shown in input lists (page count, dimensions, size)."""
    path = Path(path)
    try:
        size = human_size(path.stat().st_size)
        ext = path.suffix.lower()
        if ext == ".pdf":
            doc = load_pdf_raw(path)
            try:
                return f"Password-protected · {size}" if doc.needs_pass else f"{doc.page_count} page(s) · {size}"
            finally:
                doc.close()
        if ext in image_compress.SUPPORTED_EXTENSIONS:
            info = image_compress.image_info(path)
            return f"{info.width}×{info.height} px · {info.format} · {size}"
        return size
    except Exception as exc:  # advisory display only
        return f"Cannot read file ({str(exc)[:60]})"


def load_sheets(path: Path):
    return excel_to_pdf.list_sheets(path)


# ====================================================================================================
# Page thumbnail grid (Remove / Extract / Organize)
# ====================================================================================================

THUMB_LONG_SIDE = 220
CELL = QSize(150, 206)
ROLE = Qt.UserRole


class ThumbLoader(QThread):
    """Renders small page previews off the GUI thread."""

    count = Signal(int)
    thumb = Signal(int, QImage)
    problem = Signal(str)

    def __init__(self, path: Path) -> None:
        super().__init__()
        self._path = path
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            with open_pdf(self._path) as doc:
                self.count.emit(doc.page_count)
                for i in range(doc.page_count):
                    if self._stop:
                        return
                    page = doc[i]
                    zoom = THUMB_LONG_SIDE / max(page.rect.width, page.rect.height, 1)
                    pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
                    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
                    self.thumb.emit(i, img)
        except ToolkitError as exc:
            self.problem.emit(str(exc))
        except Exception:  # noqa: BLE001
            self.problem.emit("This PDF could not be previewed.")


class PageGrid(QListWidget):
    changed = Signal()                 # plan changed
    selectionPagesChanged = Signal(list)  # 0-based source pages of the selected items
    filesDropped = Signal(list)
    status = Signal(str)

    def __init__(self, organize: bool) -> None:
        super().__init__()
        self.organize = organize
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setWrapping(True)
        self.setFlow(QListView.LeftToRight)
        self.setUniformItemSizes(True)
        self.setIconSize(QSize(THUMB_LONG_SIDE * 3 // 5, THUMB_LONG_SIDE * 3 // 4 + 4))
        self.setGridSize(CELL)
        self.setSpacing(6)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAcceptDrops(True)
        if organize:
            self.setMovement(QListView.Static)
            self.setDragDropMode(QAbstractItemView.InternalMove)
            self.setDefaultDropAction(Qt.MoveAction)
        else:
            self.setMovement(QListView.Static)
        self._base: dict[int, QImage] = {}
        self._history: list[list[tuple[int, int]]] = []
        self._initial: list[tuple[int, int]] = []
        self._last: list[tuple[int, int]] = []
        self._loader: Optional[ThumbLoader] = None
        self.itemSelectionChanged.connect(lambda: self.selectionPagesChanged.emit(self.selected_pages()))

    # ----------------------------------------------------------------------- loading
    def load(self, path: Optional[Path]) -> None:
        self._stop_loader()
        self.clear()
        self._base.clear()
        self._history.clear()
        if path is None:
            return
        self._loader = ThumbLoader(Path(path))
        self._loader.count.connect(self._on_count)
        self._loader.thumb.connect(self._on_thumb)
        self._loader.problem.connect(self.status)
        self._loader.start()

    def _stop_loader(self) -> None:
        if self._loader is not None:
            self._loader.stop()
            self._loader.wait(3000)
            self._loader = None

    def _on_count(self, n: int) -> None:
        self.clear()
        for i in range(n):
            self._add_item(i, 0)
        self._renumber()
        self._initial = self._snapshot()
        self._last = list(self._initial)
        self.status.emit(f"{n} page(s)")

    @staticmethod
    def _with_border(img: QImage) -> QImage:
        """White pages vanish on a light background, so give every thumbnail a visible edge."""
        out = img.convertToFormat(QImage.Format_RGB32)
        p = QPainter(out)
        p.setPen(QPen(QColor("#94A3B8"), 2))
        p.drawRect(0, 0, out.width() - 1, out.height() - 1)
        p.end()
        return out

    def _on_thumb(self, index: int, img: QImage) -> None:
        img = self._with_border(img)
        self._base[index] = img
        for i in range(self.count()):
            it = self.item(i)
            if it.data(ROLE)[0] == index:
                it.setIcon(self._icon_for(*it.data(ROLE)))

    # ------------------------------------------------------------------------- items
    def _add_item(self, src: int, rot: int, row: Optional[int] = None) -> QListWidgetItem:
        it = QListWidgetItem()
        it.setData(ROLE, (src, rot))
        it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
        it.setSizeHint(CELL)
        it.setIcon(self._icon_for(src, rot))
        it.setToolTip(f"Original page {src + 1}" + (f" · rotated {rot}°" if rot else ""))
        if row is None:
            self.addItem(it)
        else:
            self.insertItem(row, it)
        return it

    def _icon_for(self, src: int, rot: int) -> QIcon:
        img = self._base.get(src)
        if img is None:
            pm = QPixmap(self.iconSize())
            pm.fill(Qt.transparent)
            return QIcon(pm)
        if rot:
            img = img.transformed(QTransform().rotate(rot), Qt.SmoothTransformation)
        pm = QPixmap.fromImage(img)
        ic = QIcon(pm)
        ic.addPixmap(pm, QIcon.Selected)  # no blue tint: the selection frame already shows the state
        return ic

    def _renumber(self) -> None:
        for i in range(self.count()):
            src, rot = self.item(i).data(ROLE)
            self.item(i).setText(f"{src + 1}" if not self.organize else f"{i + 1}")
            self.item(i).setToolTip(f"Original page {src + 1}" + (f" · rotated {rot}°" if rot else ""))

    def _snapshot(self) -> list[tuple[int, int]]:
        return [tuple(self.item(i).data(ROLE)) for i in range(self.count())]

    def _rebuild(self, plan: list[tuple[int, int]], select_rows: Optional[list[int]] = None) -> None:
        self.blockSignals(True)
        self.clear()
        for src, rot in plan:
            self._add_item(src, rot)
        self._renumber()
        for r in select_rows or []:
            if 0 <= r < self.count():
                self.item(r).setSelected(True)
        self.blockSignals(False)
        self._last = self._snapshot()
        self.changed.emit()
        self.selectionPagesChanged.emit(self.selected_pages())

    # ---------------------------------------------------------------------- queries
    def selected_pages(self) -> list[int]:
        return sorted({self.item(self.row(i)).data(ROLE)[0] for i in self.selectedItems()})

    def selected_rows(self) -> list[int]:
        return sorted(self.row(i) for i in self.selectedItems())

    def plan(self) -> list[PagePlan]:
        return [PagePlan(s, r) for s, r in self._snapshot()]

    def page_count(self) -> int:
        return len(self._base) if not self.count() else self.count()

    # ------------------------------------------------------------------ edit actions
    def _commit(self, new_plan: list[tuple[int, int]], select_rows: Optional[list[int]] = None) -> None:
        self._history.append(self._snapshot())
        self._rebuild(new_plan, select_rows)

    def rotate_selected(self, degrees: int) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        plan = self._snapshot()
        for r in rows:
            plan[r] = (plan[r][0], (plan[r][1] + degrees) % 360)
        self._commit(plan, rows)

    def delete_selected(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        if len(rows) >= self.count():
            self.status.emit("Keep at least one page.")
            return
        self._commit([p for i, p in enumerate(self._snapshot()) if i not in rows])

    def duplicate_selected(self) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        plan, out, sel = self._snapshot(), [], []
        for i, p in enumerate(plan):
            out.append(p)
            if i in rows:
                out.append(p)
                sel.append(len(out) - 1)
        self._commit(out, sel)

    def move_selected(self, delta: int) -> None:
        rows = self.selected_rows()
        if not rows:
            return
        plan = self._snapshot()
        if delta < 0 and rows[0] == 0 or delta > 0 and rows[-1] == len(plan) - 1:
            return
        order = rows if delta < 0 else reversed(rows)
        for r in order:
            plan[r], plan[r + delta] = plan[r + delta], plan[r]
        self._commit(plan, [r + delta for r in rows])

    def undo(self) -> None:
        if self._history:
            self._rebuild(self._history.pop())

    def reset_plan(self) -> None:
        if self._initial and self._snapshot() != self._initial:
            self._history.append(self._snapshot())
            self._rebuild(list(self._initial))

    def can_undo(self) -> bool:
        return bool(self._history)

    # ---------------------------------------------------------------- drag and drop
    def dragEnterEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:
        e.acceptProposedAction() if e.mimeData().hasUrls() else super().dragMoveEvent(e)

    def dropEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            self.filesDropped.emit(urls_to_paths(e.mimeData()))
            e.acceptProposedAction()
            return
        if not self.organize:
            e.ignore()
            return
        before = self._snapshot()
        super().dropEvent(e)
        after = self._snapshot()
        if after != before:
            self._history.append(before)
            self._renumber()
            self._last = after
            self.changed.emit()

    def keyPressEvent(self, e) -> None:
        if self.organize and e.key() == Qt.Key_Delete:
            self.delete_selected()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e) -> None:
        self._stop_loader()
        super().closeEvent(e)

# ====================================================================================================
# Home and category pages
# ====================================================================================================

MIN_CARD_WIDTH = 300


class CardGrid(QWidget):
    """Lays cards out in as many columns as fit; hidden cards leave no gap."""

    def __init__(self, cards: Sequence[ToolCard]) -> None:
        super().__init__()
        self.cards = list(cards)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(14)
        self._cols = 0
        self.relayout(force=True)

    def relayout(self, force: bool = False) -> None:
        cols = max(1, self.width() // MIN_CARD_WIDTH) if self.width() > 50 else 3
        if cols == self._cols and not force:
            return
        self._cols = cols
        while self._grid.count():
            self._grid.takeAt(0)
        visible = [c for c in self.cards if not c.property("filtered")]
        for i, c in enumerate(visible):
            self._grid.addWidget(c, i // cols, i % cols)
        for c in range(cols):
            self._grid.setColumnStretch(c, 1)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.relayout()


class ToolsPage(QWidget):
    """Used for Home (all categories, with search + recents) and for each single-category page."""

    toolRequested = Signal(str)

    def __init__(self, settings: AppSettings, categories: Sequence[str], title: str, subtitle: str,
                 searchable: bool, theme: str = "light") -> None:
        super().__init__()
        self.setObjectName("Page")
        self._settings = settings
        self._accent = palette(theme)["accent"]
        self._categories = list(categories)
        self._sections: list[tuple[QLabel, QLabel, CardGrid, list[ToolDef]]] = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("ScrollBody")
        scroll.setWidget(body)
        self._lay = QVBoxLayout(body)
        self._lay.setContentsMargins(32, 28, 32, 28)
        self._lay.setSpacing(10)

        h1 = QLabel(title)
        h1.setObjectName("H1")
        sub = QLabel(subtitle)
        sub.setObjectName("Sub")
        sub.setWordWrap(True)
        self._lay.addWidget(h1)
        self._lay.addWidget(sub)

        self.search: Optional[QLineEdit] = None
        if searchable:
            self.search = QLineEdit()
            self.search.setPlaceholderText("Search tools — try “merge”, “word”, “password”…")
            self.search.setClearButtonEnabled(True)
            self.search.addAction(make_icon("search", "#94A3B8", 18), QLineEdit.LeadingPosition)
            self.search.setMaximumWidth(520)
            self.search.setMinimumHeight(38)
            self.search.textChanged.connect(self._filter)
            self._lay.addSpacing(6)
            self._lay.addWidget(self.search)

        self._recent_box = QWidget()
        self._recent_lay = QVBoxLayout(self._recent_box)
        self._recent_lay.setContentsMargins(0, 8, 0, 0)
        self._lay.addWidget(self._recent_box)
        self._recent_grid: Optional[CardGrid] = None

        for cat in self._categories:
            tools = [t for t in TOOLS if t.category == cat]
            head = QLabel(cat)
            head.setObjectName("H2")
            blurb = QLabel(CATEGORY_BLURB[cat])
            blurb.setObjectName("Muted")
            grid = CardGrid([self._make_card(t) for t in tools])
            self._lay.addSpacing(10)
            self._lay.addWidget(head)
            self._lay.addWidget(blurb)
            self._lay.addWidget(grid)
            self._sections.append((head, blurb, grid, tools))
        self._lay.addStretch(1)
        self._empty = QLabel("No tools match your search.")
        self._empty.setObjectName("Muted")
        self._empty.hide()
        self._lay.insertWidget(self._lay.count() - 1, self._empty)
        if searchable:
            self.refresh_recent()

    def _make_card(self, t: ToolDef) -> ToolCard:
        c = ToolCard(t.id, t.title, t.description, t.icon, self._accent)
        c.clicked.connect(self.toolRequested)
        return c

    def refresh_recent(self) -> None:
        while self._recent_lay.count():
            w = self._recent_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)  # detach now; deleteLater alone leaves a ghost painted until the next event loop
                w.deleteLater()
        ids = [i for i in self._settings.recent_tools if i in TOOLS_BY_ID]
        self._recent_grid = None
        if not ids:
            return
        head = QLabel("Recently used")
        head.setObjectName("H2")
        self._recent_grid = CardGrid([self._make_card(TOOLS_BY_ID[i]) for i in ids])
        self._recent_lay.addWidget(head)
        self._recent_lay.addWidget(self._recent_grid)

    def _filter(self, text: str) -> None:
        q = text.strip().lower()
        self._recent_box.setVisible(not q)
        shown_any = False
        for head, blurb, grid, tools in self._sections:
            any_here = False
            for card_, t in zip(grid.cards, tools):
                hay = f"{t.title} {t.description} {t.category} {t.search_terms}".lower()
                match = all(w in hay for w in q.split()) if q else True
                card_.setProperty("filtered", not match)
                card_.setVisible(match)
                any_here |= match
            head.setVisible(any_here)
            blurb.setVisible(any_here)
            grid.setVisible(any_here)
            grid.relayout(force=True)
            shown_any |= any_here
        self._empty.setVisible(bool(q) and not shown_any)

# ====================================================================================================
# Settings and About pages
# ====================================================================================================

APP_VERSION = "1.0.0"


def _page(title: str, sub: str) -> tuple[QWidget, QVBoxLayout]:
    page = QWidget()
    page.setObjectName("Page")
    outer = QVBoxLayout(page)
    outer.setContentsMargins(0, 0, 0, 0)
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    outer.addWidget(scroll)
    body = QWidget()
    body.setObjectName("ScrollBody")
    scroll.setWidget(body)
    lay = QVBoxLayout(body)
    lay.setContentsMargins(32, 28, 32, 28)
    lay.setSpacing(12)
    h = QLabel(title)
    h.setObjectName("H1")
    s = QLabel(sub)
    s.setObjectName("Sub")
    s.setWordWrap(True)
    lay.addWidget(h)
    lay.addWidget(s)
    return page, lay


class SettingsPage(QWidget):
    themeChanged = Signal(str)

    def __init__(self, settings: AppSettings, log_path: str) -> None:
        super().__init__()
        self._settings = settings
        page, lay = _page("Settings", "Preferences are stored on this computer only. No passwords or document "
                                      "contents are ever saved.")
        QVBoxLayout(self).setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(page)

        box = card()
        form = QFormLayout(box)
        form.setContentsMargins(20, 18, 20, 18)
        form.setVerticalSpacing(14)
        self.theme = QComboBox()
        self.theme.addItem("Light", "light")
        self.theme.addItem("Dark", "dark")
        self.theme.setCurrentIndex(0 if settings.theme == "light" else 1)
        self.theme.currentIndexChanged.connect(lambda: self.themeChanged.emit(self.theme.currentData()))
        form.addRow("Theme", self.theme)
        row = QHBoxLayout()
        self.outdir = QLineEdit(settings.default_output_dir)
        self.outdir.setPlaceholderText("Same folder as the input file")
        self.outdir.editingFinished.connect(lambda: setattr(settings, "default_output_dir", self.outdir.text().strip()))
        b = button("Browse…", "small")
        b.clicked.connect(self._pick)
        row.addWidget(self.outdir, 1)
        row.addWidget(b)
        form.addRow("Default output folder", row)
        lay.addWidget(box)

        lay.addWidget(self._label("Conversion engines", "H2"))
        self.engines = card()
        self._eng_lay = QVBoxLayout(self.engines)
        self._eng_lay.setContentsMargins(20, 16, 20, 16)
        lay.addWidget(self.engines)
        self.refresh_engines()
        lay.addWidget(self._label("Log file", "H2"))
        lbl = QLabel(f"{log_path}\nLogs record errors only — never document contents or passwords.")
        lbl.setObjectName("Muted")
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lay.addWidget(lbl)
        lay.addStretch(1)

    @staticmethod
    def _label(t: str, name: str) -> QLabel:
        l = QLabel(t)
        l.setObjectName(name)
        return l

    def _pick(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Default output folder", self.outdir.text() or str(Path.home()))
        if d:
            self.outdir.setText(d)
            self._settings.default_output_dir = d

    def refresh_engines(self) -> None:
        while self._eng_lay.count():
            w = self._eng_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        so = find_soffice()
        rows = [f"PDF engine: PyMuPDF {pymupdf.__version__}  ✓", f"Images: Pillow {PIL.__version__}  ✓",
                "HTML renderer: built-in (PyMuPDF Story)  ✓"]
        for r in rows:
            self._eng_lay.addWidget(QLabel(r))
        if so:
            self._eng_lay.addWidget(QLabel(f"LibreOffice (Word / PowerPoint / Excel): found  ✓\n{so}"))
        else:
            self._eng_lay.addWidget(Banner("LibreOffice was not found. Word, PowerPoint and Excel conversion need it. "
                                           "Install the free edition from libreoffice.org, then press Re-check."))
        rc = button("Re-check", "small")
        rc.clicked.connect(self.refresh_engines)
        self._eng_lay.addWidget(rc, 0, Qt.AlignLeft)


class AboutPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        page, lay = _page("About PDF Toolkit", f"Version {APP_VERSION} · Python {sys.version.split()[0]}")
        QVBoxLayout(self).setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(page)
        for title, text in [
            ("Private by design", "Every operation runs on this computer. Files are never uploaded, there is no "
                                  "telemetry, and the app makes no network connections."),
            ("Your originals are safe", "Source files are never modified unless you explicitly choose to replace them. "
                                        "Results are written to a temporary file first and moved into place only after "
                                        "they have been verified."),
            ("Honest limits", "Word, PowerPoint and Excel are rendered by LibreOffice, so output can differ slightly from "
                              "Microsoft Office. PDF password permissions are not DRM. Modifying a PDF invalidates "
                              "digital signatures."),
            ("Open-source components", "PyMuPDF (AGPL-3.0), Pillow (HPND), openpyxl (MIT), Qt for Python / PySide6 (LGPL-3.0), "
                                       "LibreOffice (MPL-2.0, installed separately). See LICENSES.md for details and the "
                                       "obligations that apply when redistributing."),
        ]:
            c = card()
            v = QVBoxLayout(c)
            v.setContentsMargins(20, 16, 20, 16)
            h = QLabel(title)
            h.setObjectName("H2")
            t = QLabel(text)
            t.setWordWrap(True)
            t.setObjectName("Muted")
            v.addWidget(h)
            v.addWidget(t)
            lay.addWidget(c)
        lay.addStretch(1)

# ====================================================================================================
# Generic tool workspace (used by all 16 tools)
# ====================================================================================================

log = logging.getLogger("pdf_toolkit")
ROLE = Qt.UserRole


class ToolWorkspace(QWidget):
    backRequested = Signal()
    toolCompleted = Signal(str)

    def __init__(self, tool: ToolDef, settings: AppSettings) -> None:
        super().__init__()
        self.setObjectName("Page")
        self.tool = tool
        self.settings = settings
        self._thread: Optional[JobThread] = None
        self._pending: Optional[Request] = None
        self._rerun: Optional[Request] = None
        self._viewer_path: Optional[Path] = None
        self._output_edited = False
        self._last_folder: Optional[Path] = None
        self._error_details = ""
        self._opt_widgets: dict[str, QWidget] = {}
        self._opt_by_key: dict[str, Option] = {o.key: o for o in tool.options}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget()
        body.setObjectName("ScrollBody")
        scroll.setWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(32, 22, 32, 24)
        root.setSpacing(14)

        back = button("All tools", "ghost", "back", "#2563EB")
        back.clicked.connect(self.backRequested)
        root.addWidget(back, 0, Qt.AlignLeft)
        title = QLabel(tool.title)
        title.setObjectName("H1")
        desc = QLabel(tool.description)
        desc.setObjectName("Sub")
        desc.setWordWrap(True)
        root.addWidget(title)
        root.addWidget(desc)
        root.addWidget(Banner(tool.notice))

        body_row = QHBoxLayout()
        body_row.setSpacing(16)
        body_row.addWidget(self._build_inputs(), 3)
        if tool.options:
            body_row.addWidget(self._build_options(), 2)
        root.addLayout(body_row)
        root.addWidget(self._build_output())
        root.addLayout(self._build_actions())
        root.addWidget(self._build_result())
        root.addStretch(1)
        self._update_option_visibility()
        self._sync_state()

    # ================================================================== building UI
    def _build_inputs(self) -> QWidget:
        t = self.tool
        box = card()
        v = QVBoxLayout(box)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        self.input_title = QLabel("PDF pages" if t.viewer != "none" else "Files")
        self.input_title.setObjectName("H2")
        v.addWidget(self.input_title)

        self.html_mode_files = self.html_mode_text = None
        self.html_edit: Optional[QPlainTextEdit] = None
        if t.input_kind == "html":
            r = QHBoxLayout()
            self.html_mode_files = QRadioButton("HTML file")
            self.html_mode_text = QRadioButton("Type or paste HTML")
            self.html_mode_files.setChecked(True)
            self.html_mode_files.toggled.connect(self._html_mode_changed)
            r.addWidget(self.html_mode_files)
            r.addWidget(self.html_mode_text)
            r.addStretch(1)
            v.addLayout(r)

        self.list: Optional[DropListWidget] = None
        self.grid: Optional[PageGrid] = None
        self.file_label: Optional[QLabel] = None
        if t.viewer != "none":
            top = QHBoxLayout()
            self.file_label = QLabel("Drop a PDF here or choose one")
            self.file_label.setObjectName("Muted")
            self.file_label.setWordWrap(True)
            pick = button("Choose PDF…", "small", "folder")
            pick.clicked.connect(self._browse_inputs)
            top.addWidget(self.file_label, 1)
            top.addWidget(pick)
            v.addLayout(top)
            self.grid = PageGrid(organize=t.viewer == "organize")
            self.grid.setMinimumHeight(300)
            self.grid.filesDropped.connect(self._add_files)
            self.grid.selectionPagesChanged.connect(self._grid_selection)
            self.grid.changed.connect(self._sync_state)
            self.grid.status.connect(self._set_grid_status)
            v.addWidget(self.grid, 1)
            self.grid_status = QLabel("")
            self.grid_status.setObjectName("Muted")
            v.addWidget(self.grid_status)
            if t.viewer == "organize":
                v.addLayout(self._organize_toolbar())
            else:
                sel = QHBoxLayout()
                all_btn = button("Select all", "small")
                none_btn = button("Clear selection", "small")
                all_btn.clicked.connect(self.grid.selectAll)
                none_btn.clicked.connect(self.grid.clearSelection)
                sel.addWidget(all_btn)
                sel.addWidget(none_btn)
                sel.addStretch(1)
                v.addLayout(sel)
        else:
            self.list = DropListWidget(reorderable=t.reorderable)
            self.list.setMinimumHeight(240)
            self.list.filesDropped.connect(self._add_files)
            self.list.itemSelectionChanged.connect(self._sync_state)
            v.addWidget(self.list, 1)
            self.empty_hint = QLabel(self._hint_text())
            self.empty_hint.setObjectName("Muted")
            self.empty_hint.setAlignment(Qt.AlignCenter)
            self.empty_hint.setWordWrap(True)
            v.addWidget(self.empty_hint)
            row = QHBoxLayout()
            self.btn_add = button("Add files…" if t.input_kind == "files" else "Choose file…", "small", "plus")
            self.btn_add.clicked.connect(self._browse_inputs)
            row.addWidget(self.btn_add)
            self.btn_up = self.btn_down = None
            if t.reorderable:
                self.btn_up = button("Move up", "small", "up")
                self.btn_down = button("Move down", "small", "down")
                self.btn_up.clicked.connect(lambda: self._move(-1))
                self.btn_down.clicked.connect(lambda: self._move(1))
                row.addWidget(self.btn_up)
                row.addWidget(self.btn_down)
            self.btn_remove = button("Remove", "small", "trash")
            self.btn_clear = button("Clear", "small")
            self.btn_remove.clicked.connect(self._remove_selected)
            self.btn_clear.clicked.connect(self._clear_inputs)
            row.addWidget(self.btn_remove)
            row.addWidget(self.btn_clear)
            row.addStretch(1)
            v.addLayout(row)
        if t.input_kind == "html":
            self.html_edit = QPlainTextEdit()
            self.html_edit.setPlaceholderText("<h1>Hello</h1><p>Paste or type HTML here…</p>")
            self.html_edit.setMinimumHeight(240)
            self.html_edit.textChanged.connect(self._sync_state)
            self.html_edit.hide()
            v.addWidget(self.html_edit, 1)
        return box

    def _hint_text(self) -> str:
        exts = ", ".join(e.lstrip(".").upper() for e in self.tool.extensions)
        what = "files" if self.tool.input_kind == "files" else "a file"
        return f"Drag and drop {what} here, or use the button below.\nSupported: {exts}"

    def _organize_toolbar(self) -> QVBoxLayout:
        g = self.grid
        rows = [[("Rotate left", "rotate_ccw", lambda: g.rotate_selected(270)),
                 ("Rotate right", "rotate_cw", lambda: g.rotate_selected(90)),
                 ("Rotate 180°", "rotate_cw", lambda: g.rotate_selected(180)),
                 ("Move earlier", "left", lambda: g.move_selected(-1)),
                 ("Move later", "right", lambda: g.move_selected(1))],
                [("Duplicate", "copy", g.duplicate_selected), ("Delete", "trash", g.delete_selected),
                 ("Undo", "undo", g.undo), ("Reset", "", g.reset_plan)]]
        col = QVBoxLayout()
        col.setSpacing(6)
        self._org_buttons = []
        for spec in rows:
            row = QHBoxLayout()
            row.setSpacing(6)
            for text, ic, fn in spec:
                b = button(text, "small", ic)
                b.clicked.connect(fn)
                row.addWidget(b)
                self._org_buttons.append(b)
            row.addStretch(1)
            col.addLayout(row)
        return col

    def _build_options(self) -> QWidget:
        box = card()
        v = QVBoxLayout(box)
        v.setContentsMargins(18, 16, 18, 16)
        head = QLabel("Options")
        head.setObjectName("H2")
        v.addWidget(head)
        self.form = QFormLayout()
        self.form.setVerticalSpacing(12)
        self.form.setLabelAlignment(Qt.AlignLeft)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        v.addLayout(self.form)
        for o in self.tool.options:
            w = self._make_option_widget(o)
            self._opt_widgets[o.key] = w
            if o.kind == "bool":
                self.form.addRow(w)
            else:
                self.form.addRow(o.label, w)
        v.addStretch(1)
        return box

    def _make_option_widget(self, o: Option) -> QWidget:
        if o.kind == "choice":
            w = QComboBox()
            for label, value in o.choices:
                w.addItem(label, value)
            w.setCurrentIndex(max(0, w.findData(o.default)))
            w.currentIndexChanged.connect(self._option_changed)
        elif o.kind == "int":
            w = QSpinBox()
            w.setRange(o.minimum, o.maximum)
            w.setValue(o.default or 0)
            if o.special:
                w.setSpecialValueText(o.special)
            w.setSuffix(o.suffix)
            w.valueChanged.connect(self._option_changed)
        elif o.kind == "bool":
            w = QCheckBox(o.label)
            w.setChecked(bool(o.default))
            w.toggled.connect(self._option_changed)
        elif o.kind in ("text", "password"):
            w = QLineEdit(o.default or "")
            w.setPlaceholderText(o.placeholder)
            if o.kind == "password":
                w.setEchoMode(QLineEdit.Password)
                w.setToolTip(o.tooltip)
            w.textChanged.connect(self._option_changed)
        elif o.kind == "sheets":
            w = QListWidget()
            w.setMinimumHeight(110)
            w.setMaximumHeight(170)
            w.itemChanged.connect(self._option_changed)
        else:
            raise ValueError(o.kind)
        if o.tooltip:
            w.setToolTip(o.tooltip)
        return w

    def _build_output(self) -> QWidget:
        box = card()
        v = QVBoxLayout(box)
        v.setContentsMargins(18, 14, 18, 14)
        self.output_label = QLabel("Save as" if self.tool.output_kind == "file" else "Output folder")
        self.output_label.setObjectName("H2")
        v.addWidget(self.output_label)
        row = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText("Choose where to save the result")
        self.output_edit.textEdited.connect(lambda _t: setattr(self, "_output_edited", True))
        self.btn_output = button("Browse…", "", "folder")
        self.btn_output.clicked.connect(self._browse_output)
        row.addWidget(self.output_edit, 1)
        row.addWidget(self.btn_output)
        v.addLayout(row)
        return box

    def _build_actions(self) -> QVBoxLayout:
        col = QVBoxLayout()
        col.setSpacing(8)
        row = QHBoxLayout()
        self.btn_run = button(self.tool.title, "primary", "play", "#FFFFFF")
        self.btn_run.setMinimumHeight(40)
        self.btn_run.clicked.connect(lambda: self._start())
        self.btn_cancel = button("Cancel", "", "stop")
        self.btn_cancel.setMinimumHeight(40)
        self.btn_cancel.clicked.connect(self._cancel)
        self.btn_cancel.setVisible(False)
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_cancel)
        row.addStretch(1)
        col.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        col.addWidget(self.progress)
        col.addWidget(self.status)
        return col

    def _build_result(self) -> QWidget:
        self.result_box = card()
        v = QVBoxLayout(self.result_box)
        v.setContentsMargins(18, 16, 18, 16)
        self.result_title = QLabel("")
        self.result_title.setObjectName("H2")
        self.result_msg = QLabel("")
        self.result_msg.setWordWrap(True)
        self.result_msg.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.result_warn = Banner("")
        self.result_table = QTableWidget()
        self.result_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.result_table.verticalHeader().hide()
        self.result_table.hide()
        v.addWidget(self.result_title)
        v.addWidget(self.result_msg)
        v.addWidget(self.result_table)
        v.addWidget(self.result_warn)
        row = QHBoxLayout()
        self.btn_open = button("Open output folder", "primary", "folder", "#FFFFFF")
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_details = button("Error details…", "")
        self.btn_details.clicked.connect(self._show_details)
        row.addWidget(self.btn_open)
        row.addWidget(self.btn_details)
        row.addStretch(1)
        v.addLayout(row)
        self.result_box.hide()
        return self.result_box

    # ================================================================= input handling
    def _html_mode_changed(self) -> None:
        text_mode = bool(self.html_mode_text and self.html_mode_text.isChecked())
        self.list.setVisible(not text_mode)
        self.empty_hint.setVisible(not text_mode and self.list.count() == 0)
        self.btn_add.setVisible(not text_mode)
        self.btn_remove.setVisible(not text_mode)
        self.btn_clear.setVisible(not text_mode)
        self.html_edit.setVisible(text_mode)
        self._sync_state()

    def _filter_paths(self, paths: list[Path]) -> list[Path]:
        ok = [p for p in paths if p.is_file() and p.suffix.lower() in self.tool.extensions]
        bad = len(paths) - len(ok)
        if bad:
            self._info(f"Skipped {bad} item(s) that are not supported by this tool.")
        return ok

    def _browse_inputs(self) -> None:
        exts = " ".join(f"*{e}" for e in self.tool.extensions)
        start = self.settings.last_output_dir or str(Path.home())
        if self.tool.input_kind == "files":
            files, _ = QFileDialog.getOpenFileNames(self, "Select files", start, f"Supported files ({exts})")
        else:
            f, _ = QFileDialog.getOpenFileName(self, "Select a file", start, f"Supported files ({exts})")
            files = [f] if f else []
        if files:
            self._add_files([Path(f) for f in files])

    def _add_files(self, paths: list[Path]) -> None:
        if self._busy():
            return
        paths = self._filter_paths(paths)
        if not paths:
            return
        if self.tool.viewer != "none" or self.tool.input_kind != "files":
            self._set_single(paths[0])
            return
        for p in paths:
            it = QListWidgetItem(f"{p.name}\n{describe_file(p)}")
            it.setData(ROLE, str(p))
            it.setToolTip(str(p))
            self.list.addItem(it)
        self._inputs_changed()

    def _set_single(self, p: Path) -> None:
        self._clear_result()
        if self.grid is not None:
            self._viewer_path = p
            self.file_label.setText(f"{p.name} — {describe_file(p)}")
            self.grid.load(p)
        else:
            self.list.clear()
            it = QListWidgetItem(f"{p.name}\n{describe_file(p)}")
            it.setData(ROLE, str(p))
            it.setToolTip(str(p))
            self.list.addItem(it)
        self._inputs_changed()

    def _move(self, delta: int) -> None:
        rows = sorted(self.list.row(i) for i in self.list.selectedItems())
        if not rows or (delta < 0 and rows[0] == 0) or (delta > 0 and rows[-1] == self.list.count() - 1):
            return
        for r in (rows if delta < 0 else reversed(rows)):
            it = self.list.takeItem(r)
            self.list.insertItem(r + delta, it)
        for r in rows:
            self.list.item(r + delta).setSelected(True)

    def _remove_selected(self) -> None:
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))
        self._inputs_changed()

    def _clear_inputs(self) -> None:
        self.list.clear()
        self._inputs_changed()

    def _inputs_changed(self) -> None:
        if self.list is not None:
            self.empty_hint.setVisible(self.list.count() == 0 and not (self.html_edit and self.html_edit.isVisible()))
        if "sheets" in self._opt_widgets:
            self._load_sheets()
        if not self._output_edited:
            self._suggest_output()
        self._sync_state()

    def _current_inputs(self) -> list[Path]:
        if self.grid is not None:
            return [self._viewer_path] if self._viewer_path else []
        if self.list is None:
            return []
        return [Path(self.list.item(i).data(ROLE)) for i in range(self.list.count())]

    def _grid_selection(self, pages: list[int]) -> None:
        w = self._opt_widgets.get("pages")
        if self.tool.viewer == "select" and isinstance(w, QLineEdit):
            w.setText(pages_to_spec(pages))

    def _set_grid_status(self, text: str) -> None:
        self.grid_status.setText(text)

    def _load_sheets(self) -> None:
        w: QListWidget = self._opt_widgets["sheets"]  # type: ignore[assignment]
        w.blockSignals(True)
        w.clear()
        inputs = self._current_inputs()
        if inputs and inputs[0].suffix.lower() == ".xlsx":
            try:
                for s in load_sheets(inputs[0]):
                    it = QListWidgetItem(s.name + ("  (hidden)" if s.hidden else ""))
                    it.setData(ROLE, s.name)
                    it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
                    it.setCheckState(Qt.Unchecked if s.hidden else Qt.Checked)
                    w.addItem(it)
                self._info("")
            except ToolkitError as exc:
                self._info(str(exc))
        elif inputs:
            it = QListWidgetItem("Sheet selection is available for .xlsx files only")
            it.setFlags(Qt.NoItemFlags)
            w.addItem(it)
        w.blockSignals(False)

    # =================================================================== options/output
    def _option_changed(self, *_a: Any) -> None:
        self._update_option_visibility()
        self._sync_state()

    def _raw_options(self, with_secrets: bool = True) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, w in self._opt_widgets.items():
            o = self._opt_by_key[key]
            if isinstance(w, QComboBox):
                out[key] = w.currentData()
            elif isinstance(w, QSpinBox):
                out[key] = w.value()
            elif isinstance(w, QCheckBox):
                out[key] = w.isChecked()
            elif isinstance(w, QLineEdit):
                out[key] = w.text() if o.kind == "password" else w.text().strip()
            elif isinstance(w, QListWidget):
                names = [(w.item(i).data(ROLE), w.item(i).checkState() == Qt.Checked)
                         for i in range(w.count()) if w.item(i).data(ROLE)]
                chosen = [n for n, c in names if c]
                out[key] = None if (not names or len(chosen) == len(names)) else chosen
        return out

    def _update_option_visibility(self) -> None:
        if not hasattr(self, "form"):
            return
        vals = self._raw_options()
        for o in self.tool.options:
            if o.show_if is not None:
                self.form.setRowVisible(self._opt_widgets[o.key], bool(o.show_if(vals)))
        if self.tool.output_disabled_if:
            off = bool(self.tool.output_disabled_if(vals))
            self.output_edit.setEnabled(not off)
            self.btn_output.setEnabled(not off)

    def _base_dir(self, inputs: list[Path]) -> Path:
        if self.settings.default_output_dir and Path(self.settings.default_output_dir).is_dir():
            return Path(self.settings.default_output_dir)
        if inputs:
            return inputs[0].parent
        if self.settings.last_output_dir:
            return Path(self.settings.last_output_dir)
        return Path.home() / "Documents" if (Path.home() / "Documents").is_dir() else Path.home()

    def _suggest_output(self) -> None:
        inputs = self._current_inputs()
        if not inputs and not (self.html_edit and self.html_edit.toPlainText().strip()):
            return
        name = sanitize_filename(self.tool.default_output(inputs, self._raw_options()), "output")
        self.output_edit.setText(str(self._base_dir(inputs) / name))

    def _browse_output(self) -> None:
        cur = self.output_edit.text() or str(self._base_dir(self._current_inputs()))
        if self.tool.output_kind == "folder":
            d = QFileDialog.getExistingDirectory(self, "Choose output folder", cur if Path(cur).is_dir() else str(Path(cur).parent))
            if d:
                self.output_edit.setText(str(Path(d)))
                self._output_edited = True
        else:
            f, _ = QFileDialog.getSaveFileName(self, "Save as", cur, "PDF (*.pdf)", options=QFileDialog.DontConfirmOverwrite)
            if f:
                self.output_edit.setText(f if f.lower().endswith(self.tool.output_ext) else f + self.tool.output_ext)
                self._output_edited = True

    # ======================================================================= running
    def _busy(self) -> bool:
        return self._thread is not None

    def _sync_state(self) -> None:
        busy = self._busy()
        has_input = bool(self._current_inputs()) or bool(self.html_edit and self.html_edit.isVisible()
                                                         and self.html_edit.toPlainText().strip())
        self.btn_run.setEnabled(has_input and not busy)
        if self.list is not None:
            for b in (self.btn_add, self.btn_remove, self.btn_clear, self.btn_up, self.btn_down):
                if b is not None:
                    b.setEnabled(not busy)
        if self.grid is not None and self.tool.viewer == "organize":
            for b in self._org_buttons:
                b.setEnabled(not busy)
        self.btn_output.setEnabled(not busy)

    def _fail_validation(self, msg: str) -> None:
        self._show_result(False, "Please check your settings", msg, [], None)

    def _start(self, overwrite: bool = False, request: Optional[Request] = None) -> None:
        if self._busy():
            return
        self._clear_result()
        t = self.tool
        if request is None:
            inputs = self._current_inputs()
            html_text = None
            if t.input_kind == "html" and self.html_mode_text.isChecked():
                html_text = self.html_edit.toPlainText()
                inputs = []
            if not inputs and html_text is None:
                return self._fail_validation("Add at least one file first.")
            if len(inputs) < t.min_inputs and html_text is None:
                return self._fail_validation(f"Add at least {t.min_inputs} files to use {t.title}.")
            opts = self._raw_options()
            if t.validate and (msg := t.validate(inputs, opts)):
                return self._fail_validation(msg)
            if t.confirm and (q := t.confirm(opts)) and not confirm(self, t.title, q, "Yes, replace originals"):
                return
            out_text = self.output_edit.text().strip()
            disabled = bool(t.output_disabled_if and t.output_disabled_if(opts))
            if not out_text and not disabled:
                return self._fail_validation("Choose where to save the result.")
            out = Path(out_text) if out_text else Path()
            if t.output_kind == "file" and out_text and out.suffix.lower() != t.output_ext:
                out = out.with_name(out.name + t.output_ext)
            plan = None
            if t.viewer == "organize":
                plan = self.grid.plan()
                if not plan:
                    return self._fail_validation("Keep at least one page.")
            request = Request(inputs, out, opts, overwrite, plan, html_text)
        else:
            request.overwrite = overwrite
        self._pending = request
        req = request
        self._thread = JobThread(lambda ctx: t.run(req, ctx))
        self._thread.progress.connect(self._on_progress)
        self._thread.succeeded.connect(self._on_success)
        self._thread.failed.connect(self._on_failed)
        self._thread.finished.connect(self._on_thread_finished)
        self.progress.setRange(0, 0)
        self.progress.show()
        self.status.setText("Working…")
        self.btn_cancel.setVisible(True)
        self.btn_cancel.setEnabled(t.cancellable)
        self.btn_run.setEnabled(False)
        self._sync_state()
        self._thread.start()

    def _cancel(self) -> None:
        if self._thread:
            self._thread.cancel()
            self.status.setText("Cancelling…")
            self.btn_cancel.setEnabled(False)

    def _on_progress(self, done: int, total: int, msg: str) -> None:
        if total <= 0:
            self.progress.setRange(0, 0)
        else:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        self.status.setText(msg + (f"  ({done + 1} of {total})" if total > 0 and done < total else ""))

    def _on_thread_finished(self) -> None:
        if self._thread:
            self._thread.deleteLater()
        self._thread = None
        self.progress.hide()
        self.btn_cancel.setVisible(False)
        self._sync_state()
        if self._rerun is not None:
            req, self._rerun = self._rerun, None
            self._start(True, req)

    def _on_success(self, res: Result) -> None:
        missing = [p for p in res.outputs if not Path(p).exists()]
        if missing:  # never report success unless the output really exists
            return self._show_result(False, "The result could not be verified",
                                     f"Expected output is missing: {missing[0].name}", [], None)
        for key in ("password", "confirm", "owner"):  # do not keep secrets in the UI after use
            w = self._opt_widgets.get(key)
            if isinstance(w, QLineEdit) and self._opt_by_key[key].kind == "password":
                w.clear()
        folder = None
        if res.outputs:
            folder = Path(res.outputs[0]).parent
        elif self._pending and self._pending.inputs:
            folder = self._pending.inputs[0].parent  # e.g. originals replaced in place
        self._last_folder = folder
        if folder:
            self.settings.last_output_dir = str(folder)
        table = self.tool.result_table(res) if self.tool.result_table else None
        self._show_result(True, "Done", res.message, res.warnings, table)
        self.toolCompleted.emit(self.tool.id)
        self._pending = None

    def _on_failed(self, exc: BaseException, tb: str) -> None:
        if isinstance(exc, OutputExistsError) and self._pending is not None:
            req = self._pending
            if confirm_overwrite(self, exc.paths):
                self._rerun = req  # restarted in _on_thread_finished, once this worker has fully stopped
                return
            self.status.setText("Cancelled — nothing was replaced.")
            self._pending = None
            return
        self._pending = None
        if isinstance(exc, OperationCancelled):
            self.status.setText("Cancelled. No output was created.")
            return
        if isinstance(exc, ToolkitError):
            self._error_details = f"{type(exc).__name__}: {exc}"
            self._show_result(False, "Could not complete the operation", str(exc), [], None, details=True)
        else:
            self._error_details = tb or f"{type(exc).__name__}: {exc}"
            self._show_result(False, "Something unexpected went wrong",
                              "The operation failed and your original files were not changed. "
                              "Technical details are available below and in the log file.", [], None, details=True)

    # ======================================================================= results
    def _clear_result(self) -> None:
        self.result_box.hide()
        self.status.setText("")

    def _show_result(self, ok: bool, title: str, msg: str, warnings: list[str],
                     table: Optional[tuple[list[str], list[list[str]]]], details: bool = False) -> None:
        self.result_title.setText(("✓  " if ok else "✕  ") + title)
        self.result_title.setStyleSheet(f"color: {'#067647' if ok else '#B42318'};")
        self.result_msg.setText(msg)
        self.result_warn.setText("Notes\n" + "\n".join(f"• {w}" for w in warnings) if warnings else "")
        self.result_warn.setVisible(bool(warnings))
        if table and table[1]:
            heads, rows = table
            self.result_table.setColumnCount(len(heads))
            self.result_table.setHorizontalHeaderLabels(heads)
            self.result_table.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, val in enumerate(row):
                    self.result_table.setItem(r, c, QTableWidgetItem(val))
            self.result_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
            self.result_table.setFixedHeight(min(260, 40 + 30 * len(rows)))
            self.result_table.show()
        else:
            self.result_table.hide()
        self.btn_open.setVisible(ok and self._last_folder is not None)
        self.btn_details.setVisible(details)
        self.result_box.show()
        self.status.setText("")

    def _open_folder(self) -> None:
        if self._last_folder and Path(self._last_folder).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_folder)))

    def _show_details(self) -> None:
        ErrorDetailsDialog(self, "Technical details (contain no document contents or passwords):",
                           self._error_details).exec()

    def _info(self, text: str) -> None:
        self.status.setText(text)

    def reset_for_show(self) -> None:
        """Called when the user opens the tool again."""
        if not self._busy():
            self.result_box.hide()

# ====================================================================================================
# Main window
# ====================================================================================================

NAV_ITEMS = [("Home", "home"), *[(c, i) for c, i in zip(
    CATEGORIES, ["merge", "image", "pdf2img", "lock", "compress_img"])], ("Settings", "settings"), ("About", "info")]


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, log_path: str = "") -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("PDF Toolkit")
        self.setWindowIcon(QIcon(logo_pixmap(128)))
        self.setMinimumSize(980, 660)
        self.resize(1220, 780)
        self._workspaces: dict[str, ToolWorkspace] = {}
        self._nav: dict[str, QPushButton] = {}
        self._pages: dict[str, QWidget] = {}
        accent = palette(settings.theme)["accent"]

        central = QWidget()
        self.setCentralWidget(central)
        row = QHBoxLayout(central)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(230)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(14, 18, 14, 14)
        sv.setSpacing(4)
        brand = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(logo_pixmap(34))
        name = QLabel("PDF Toolkit")
        name.setObjectName("AppName")
        brand.addWidget(logo)
        brand.addWidget(name, 1)
        sv.addLayout(brand)
        sv.addSpacing(16)
        for label, ic in NAV_ITEMS:
            if label == "Settings":
                sv.addStretch(1)
            b = QPushButton(label)
            b.setObjectName("Nav")
            b.setCheckable(True)
            b.setIcon(make_icon(ic, "#64748B", 20, checked_color=accent))
            b.setIconSize(QSize(20, 20))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c=False, l=label: self.show_page(l))
            sv.addWidget(b)
            self._nav[label] = b
        row.addWidget(side)

        self.stack = QStackedWidget()
        row.addWidget(self.stack, 1)

        home = ToolsPage(settings, CATEGORIES, "What would you like to do?",
                         "16 tools for PDFs, documents and images — everything runs on this computer.", True,
                         settings.theme)
        self._register("Home", home)
        for cat in CATEGORIES:
            self._register(cat, ToolsPage(settings, [cat], cat, CATEGORY_BLURB[cat], False, settings.theme))
        self.settings_page = SettingsPage(settings, log_path)
        self.settings_page.themeChanged.connect(self.apply_theme)
        self._register("Settings", self.settings_page)
        self._register("About", AboutPage())
        for page in self._pages.values():
            if isinstance(page, ToolsPage):
                page.toolRequested.connect(self.open_tool)
        self.show_page("Home")

    def _register(self, name: str, page: QWidget) -> None:
        self._pages[name] = page
        self.stack.addWidget(page)

    def _highlight(self, name: str) -> None:
        for n, b in self._nav.items():
            b.setChecked(n == name)

    def show_page(self, name: str) -> None:
        self._highlight(name)
        page = self._pages[name]
        if name == "Home":
            page.refresh_recent()
        if name == "Settings":
            page.refresh_engines()
        self.stack.setCurrentWidget(page)

    def open_tool(self, tool_id: str) -> None:
        tool = TOOLS_BY_ID[tool_id]
        ws = self._workspaces.get(tool_id)
        if ws is None:
            ws = ToolWorkspace(tool, self.settings)
            ws.backRequested.connect(lambda c=tool.category: self.show_page(c))
            ws.toolCompleted.connect(self.settings.push_recent)
            self._workspaces[tool_id] = ws
            self.stack.addWidget(ws)
        ws.reset_for_show()
        self._highlight(tool.category)
        self.stack.setCurrentWidget(ws)

    def apply_theme(self, theme: str) -> None:
        self.settings.theme = theme
        QApplication.instance().setStyleSheet(stylesheet(theme))

    def closeEvent(self, e) -> None:
        busy = [w for w in self._workspaces.values() if w._busy()]
        if busy:
            if not confirm(self, "Operation in progress",
                           "An operation is still running. Closing now will cancel it. Close anyway?", "Close"):
                e.ignore()
                return
            for w in busy:
                w._cancel()
                if w._thread:
                    w._thread.wait(5000)
        for w in self._workspaces.values():  # stop thumbnail threads before Qt tears down
            if w.grid is not None:
                w.grid._stop_loader()
        super().closeEvent(e)

# ====================================================================================================
# Entry point
# ====================================================================================================


def _log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "PDFToolkit" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "pdf_toolkit.log"


def setup_logging() -> str:
    path = _log_path()
    handler = RotatingFileHandler(path, maxBytes=500_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger("pdf_toolkit")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return str(path)


def selftest() -> int:
    """Headless check that the engines work: `python main.py --selftest`."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for n in "ab":
            doc = pymupdf.open()
            doc.new_page().insert_text((72, 72), f"selftest {n}")
            doc.save(d / f"{n}.pdf")
        merge_pdf.merge_pdfs([d / "a.pdf", d / "b.pdf"], d / "m.pdf")
        pdf_to_image.pdf_to_images(d / "m.pdf", d / "img", dpi=72)
        html_to_pdf.html_to_pdf(d / "h.pdf", html_text="<h1>ok</h1>")
        protect_pdf.protect_pdf(d / "m.pdf", d / "p.pdf", "pw")
        unlock_pdf.unlock_pdf(d / "p.pdf", d / "u.pdf", "pw")
        Image.new("RGB", (400, 300), "white").save(d / "x.jpg")
        image_compress.compress_images([d / "x.jpg"], d / "c", image_compress.CompressOptions(quality=50, max_width=200))
        print("selftest OK; LibreOffice:", find_soffice() or "not found")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    log_path = setup_logging()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Toolkit")
    app.setOrganizationName("PDFToolkit")

    def excepthook(et, ev, tb):  # last resort: never show a raw traceback to the user
        logging.getLogger("pdf_toolkit").error("Unhandled %s", et.__name__, exc_info=(et, ev, tb))
        QMessageBox.critical(None, "PDF Toolkit", "An unexpected error occurred. Your files were not changed.\n"
                                                  f"Details were written to:\n{log_path}")

    sys.excepthook = excepthook
    settings = AppSettings()
    app.setStyleSheet(stylesheet(settings.theme))
    win = MainWindow(settings, log_path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

