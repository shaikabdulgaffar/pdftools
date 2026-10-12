from __future__ import annotations

from pathlib import Path
from typing import Sequence

from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel, QMessageBox, QPlainTextEdit, QPushButton,
                               QVBoxLayout, QWidget)


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
