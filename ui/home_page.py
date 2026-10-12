"""Home page and category pages: heading, search and tool cards."""
from __future__ import annotations

from typing import Optional, Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from app import icons
from app.settings import AppSettings
from app.theme import palette
from app.tools import CATEGORIES, CATEGORY_BLURB, TOOLS, TOOLS_BY_ID, ToolDef
from ui.widgets import ToolCard

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
            self.search.addAction(icons.icon("search", "#94A3B8", 18), QLineEdit.LeadingPosition)
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
