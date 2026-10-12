"""PDF Toolkit entry point."""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def _log_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "PDFToolkit" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "pdf_toolkit.log"


def setup_logging() -> str:
    path = _log_path()
    handler = RotatingFileHandler(path, maxBytes=500_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger("pdf_toolkit")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return str(path)


def selftest() -> int:
    """Headless check that the bundled engines work (run `PDFToolkit.exe --selftest` on a clean machine)."""
    import tempfile

    import pymupdf
    from PIL import Image

    from core import (html_to_pdf, image_compress, pdf_merge, pdf_security, pdf_to_image)

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for n in "ab":
            doc = pymupdf.open()
            doc.new_page().insert_text((72, 72), f"selftest {n}")
            doc.save(d / f"{n}.pdf")
        pdf_merge.merge_pdfs([d / "a.pdf", d / "b.pdf"], d / "m.pdf")
        pdf_to_image.pdf_to_images(d / "m.pdf", d / "img", dpi=72)
        html_to_pdf.html_to_pdf(d / "h.pdf", html_text="<h1>ok</h1>")
        pdf_security.protect_pdf(d / "m.pdf", d / "p.pdf", "pw")
        pdf_security.unlock_pdf(d / "p.pdf", d / "u.pdf", "pw")
        Image.new("RGB", (400, 300), "white").save(d / "x.jpg")
        image_compress.compress_images([d / "x.jpg"], d / "c", image_compress.CompressOptions(quality=50, max_width=200))
        from PySide6.QtSvg import QSvgRenderer  # noqa: F401  (icons)
        from core.office_engine import find_soffice
        print("selftest OK; LibreOffice:", find_soffice() or "not found")
    return 0


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    log_path = setup_logging()
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("PDF Toolkit")
    app.setOrganizationName("PDFToolkit")

    from app.main_window import MainWindow
    from app.settings import AppSettings
    from app.theme import stylesheet

    def excepthook(et, ev, tb):  # last resort: never show a raw traceback to the user
        logging.getLogger("pdf_toolkit").error("Unhandled %s", et.__name__, exc_info=(et, ev, tb))
        QMessageBox.critical(None, "PDF Toolkit", "An unexpected error occurred. Your files were not changed.\n"
                                                  f"Details were written to:\n{log_path}")

    sys.excepthook = excepthook
    settings = AppSettings()
    app.setStyleSheet(stylesheet(settings.theme))
    win = MainWindow(settings, log_path)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
