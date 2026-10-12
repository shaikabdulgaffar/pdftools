"""Background execution. Workers never touch widgets: they only emit signals."""
from __future__ import annotations

import logging
import traceback
from typing import Any, Callable

from PySide6.QtCore import QThread, Signal

from core.common import JobContext, OperationCancelled, Result

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
            from core.common import ToolkitError
            tb = "" if isinstance(exc, ToolkitError) else traceback.format_exc()
            if tb:
                log.error("Unexpected %s in worker\n%s", type(exc).__name__, tb)  # no document content / passwords
            self.failed.emit(exc, tb)
