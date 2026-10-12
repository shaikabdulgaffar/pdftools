"""Main window: sidebar navigation + stacked pages (home, categories, tool workspaces, settings, about)."""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
                               QVBoxLayout, QWidget)

from app import icons
from app.settings import AppSettings
from app.theme import palette, stylesheet
from app.tools import CATEGORIES, CATEGORY_BLURB, TOOLS_BY_ID
from ui.home_page import ToolsPage
from ui.info_pages import AboutPage, SettingsPage
from ui.tool_workspace import ToolWorkspace

NAV_ITEMS = [("Home", "home"), *[(c, i) for c, i in zip(
    CATEGORIES, ["merge", "image", "pdf2img", "lock", "compress_img"])], ("Settings", "settings"), ("About", "info")]


class MainWindow(QMainWindow):
    def __init__(self, settings: AppSettings, log_path: str = "") -> None:
        super().__init__()
        self.settings = settings
        self.setWindowTitle("PDF Toolkit")
        self.setWindowIcon(QIcon(icons.logo_pixmap(128)))
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
        logo.setPixmap(icons.logo_pixmap(34))
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
            b.setIcon(icons.icon(ic, "#64748B", 20, checked_color=accent))
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
            from app.dialogs import confirm
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
