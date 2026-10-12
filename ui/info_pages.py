"""Settings and About pages."""
from __future__ import annotations

import sys
from pathlib import Path

import PIL
import pymupdf
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QVBoxLayout, QWidget)

from app.settings import AppSettings
from core.office_engine import find_soffice
from ui.widgets import Banner, button, card

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
