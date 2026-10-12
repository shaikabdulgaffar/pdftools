"""Non-sensitive preferences only (theme, folders, recent tools). Passwords and document contents are never stored."""
from __future__ import annotations

from PySide6.QtCore import QSettings


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
