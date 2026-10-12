# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for PDF Toolkit.

Build (from the project root, inside the virtual environment):

    pyinstaller packaging/pdf_toolkit.spec --noconfirm --clean              # one-folder build (recommended)
    set PDFTOOLKIT_ONEFILE=1 && pyinstaller packaging/pdf_toolkit.spec --noconfirm --clean   # optional one-file

Output: dist/PDFToolkit/PDFToolkit.exe (one-folder) or dist/PDFToolkit.exe (one-file).

NOT bundled (by design - see LICENSES.md / README): LibreOffice. Word, PowerPoint and Excel conversion look for
it on the user's computer at run time and explain how to install it if it is missing.
"""
import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent
ICON = ROOT / "resources" / "icons" / "app.ico"
ONEFILE = os.environ.get("PDFTOOLKIT_ONEFILE") == "1"

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "resources"), "resources"), (str(ROOT / "LICENSES.md"), "."), (str(ROOT / "README.md"), ".")],
    hiddenimports=["PySide6.QtSvg"],            # icons are rendered from SVG
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore",
              "PySide6.QtQuick", "PySide6.QtQml", "PySide6.QtMultimedia", "PySide6.QtCharts",
              "PySide6.QtDataVisualization", "PySide6.QtPdf", "PySide6.QtPdfWidgets", "pytest", "docx", "pptx"],
    noarchive=False,
)
pyz = PYZ(a.pure)

common = dict(name="PDFToolkit", debug=False, strip=False, upx=False,   # UPX often triggers antivirus false positives
              console=False, icon=str(ICON) if ICON.exists() and sys.platform == "win32" else None)

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **common)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **common)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="PDFToolkit")
