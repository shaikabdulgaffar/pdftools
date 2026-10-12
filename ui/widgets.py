"""Small reusable widgets."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout,
                               QWidget)

from app import icons


def set_variant(btn: QPushButton, variant: str) -> QPushButton:
    btn.setProperty("variant", variant)
    btn.style().unpolish(btn)
    btn.style().polish(btn)
    return btn


def button(text: str, variant: str = "", icon_name: str = "", icon_color: str = "#64748B") -> QPushButton:
    b = QPushButton(text)
    if icon_name:
        b.setIcon(icons.icon(icon_name, icon_color, 18))
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
        ic.setPixmap(icons.icon(icon_name, accent, 26).pixmap(26, 26))
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
