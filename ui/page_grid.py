"""Thumbnail grid of PDF pages for Remove / Extract (selection) and Organize (reorder, rotate, duplicate, delete)."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pymupdf
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPen, QPixmap, QTransform
from PySide6.QtWidgets import QAbstractItemView, QListView, QListWidget, QListWidgetItem

from core.common import ToolkitError, open_pdf
from core.pdf_organize import PagePlan
from ui.widgets import urls_to_paths

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
