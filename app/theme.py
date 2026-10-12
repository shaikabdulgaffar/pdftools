"""Light / dark Qt stylesheets."""
from __future__ import annotations

from string import Template

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
