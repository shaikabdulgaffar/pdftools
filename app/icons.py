"""Original line icons (24x24 grid, drawn for this project) rendered from inline SVG."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_DOC = '<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/>'
_PATHS: dict[str, str] = {
    "home": '<path d="M4 11 12 4l8 7"/><path d="M6 10v10h12V10"/><path d="M10 20v-5h4v5"/>',
    "merge": '<path d="M12 3 3 8l9 5 9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 16 9 5 9-5"/>',
    "split": '<path d="M12 3v8"/><path d="m12 11-6 7"/><path d="m12 11 6 7"/><path d="M4 18h4M16 18h4"/>',
    "remove": _DOC + '<path d="M9.5 14h5"/>',
    "extract": _DOC + '<path d="M12 18v-6"/><path d="m9.5 14.5 2.5-2.5 2.5 2.5"/>',
    "organize": '<rect x="4" y="4" width="7" height="7" rx="1.5"/><rect x="13" y="4" width="7" height="7" rx="1.5"/>'
                '<rect x="4" y="13" width="7" height="7" rx="1.5"/><rect x="13" y="13" width="7" height="7" rx="1.5"/>',
    "compress": '<path d="m4 4 6 6"/><path d="M10 5v5H5"/><path d="m20 20-6-6"/><path d="M14 19v-5h5"/>',
    "compress_img": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m4 18 5-5 3 3 3-3 5 5"/>'
                    '<path d="m14 7 2 2M18 7l-2 2"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="m4 18 5-5 4 4 3-3 4 4"/>',
    "word": _DOC + '<path d="m8.5 12 1.5 6 2-5.5 2 5.5 1.5-6"/>',
    "ppt": _DOC + '<path d="M9.5 18v-6h3a2 2 0 0 1 0 4h-3"/>',
    "excel": _DOC + '<path d="m9.5 12 5 6M14.5 12l-5 6"/>',
    "html": '<path d="m8 8-5 4 5 4"/><path d="m16 8 5 4-5 4"/><path d="m13.5 5-3 14"/>',
    "pdf2img": _DOC + '<path d="m8.5 18 2.5-3 2 2 1.5-1.5 1.5 2.5"/>',
    "raster": '<path d="M4 12a8 8 0 0 1 14-5"/><path d="M18 3v4h-4"/><path d="M20 12a8 8 0 0 1-14 5"/><path d="M6 21v-4h4"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "unlock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
    "settings": '<path d="M4 7h10M18 7h2M4 17h2M10 17h10"/><circle cx="16" cy="7" r="2"/><circle cx="8" cy="17" r="2"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><path d="M12 7.5v.01"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "search": '<circle cx="11" cy="11" r="6"/><path d="m20 20-4.5-4.5"/>',
    "back": '<path d="m15 5-7 7 7 7"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "up": '<path d="m6 15 6-6 6 6"/>',
    "down": '<path d="m6 9 6 6 6-6"/>',
    "left": '<path d="m15 6-6 6 6 6"/>',
    "right": '<path d="m9 6 6 6-6 6"/>',
    "trash": '<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="m6 7 1 13h10l1-13"/>',
    "rotate_cw": '<path d="M19 12a7 7 0 1 1-2.5-5.4"/><path d="M19 4v4h-4"/>',
    "rotate_ccw": '<path d="M5 12a7 7 0 1 0 2.5-5.4"/><path d="M5 4v4h4"/>',
    "copy": '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "check": '<path d="m5 12 5 5 9-10"/>',
    "alert": '<path d="M12 4 2.5 20h19z"/><path d="M12 10v5"/><path d="M12 17.5v.01"/>',
    "x": '<path d="m6 6 12 12M18 6 6 18"/>',
    "stop": '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    "play": '<path d="m8 5 11 7-11 7z"/>',
}

_cache: dict[tuple, QIcon] = {}


def _render(name: str, color: str, px: int) -> QPixmap:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
           f'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{_PATHS[name]}</svg>')
    scale = 2  # crisp on high-DPI screens
    pm = QPixmap(px * scale, px * scale)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pm.setDevicePixelRatio(scale)
    return pm


def icon(name: str, color: str = "#64748B", size: int = 24, checked_color: str | None = None) -> QIcon:
    key = (name, color, size, checked_color)
    if key not in _cache:
        ic = QIcon()
        ic.addPixmap(_render(name, color, size), QIcon.Normal, QIcon.Off)
        ic.addPixmap(_render(name, color, size), QIcon.Disabled, QIcon.Off)
        ic.addPixmap(_render(name, checked_color or color, size), QIcon.Normal, QIcon.On)
        _cache[key] = ic
    return _cache[key]


def logo_pixmap(px: int = 64) -> QPixmap:
    """App logo: blue rounded square with a white page."""
    scale = 2
    pm = QPixmap(px * scale, px * scale)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(Qt.GlobalColor.transparent)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="15" '
           f'fill="#2563EB"/><path d="M20 12h17l9 9v31H20z" fill="#fff"/><path d="M37 12v9h9" fill="#C7D7FB"/>'
           f'<rect x="26" y="34" width="14" height="3" rx="1.5" fill="#2563EB"/>'
           f'<rect x="26" y="41" width="10" height="3" rx="1.5" fill="#93B4F8"/></svg>')
    QSvgRenderer(QByteArray(svg.encode())).render(p)
    p.end()
    pm.setDevicePixelRatio(scale)
    return pm
