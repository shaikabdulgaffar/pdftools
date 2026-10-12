"""Generic, data-driven workspace used by all 16 tools.

Layout: inputs (drop zone / list or page thumbnails) | options, then output, action bar, progress and result.
All processing runs in a JobThread; this class only reacts to its signals.
"""
from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any, Optional

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPlainTextEdit,
                               QProgressBar, QRadioButton, QScrollArea, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from app import icons
from app.dialogs import ErrorDetailsDialog, confirm, confirm_overwrite
from app.settings import AppSettings
from app.tools import Option, Request, ToolDef, describe_file, load_sheets
from app.workers import JobThread
from core.common import (OperationCancelled, OutputExistsError, Result, ToolkitError, pages_to_spec, sanitize_filename)
from ui.page_grid import PageGrid
from ui.widgets import Banner, DropListWidget, button, card

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

