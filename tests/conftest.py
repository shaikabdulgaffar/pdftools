"""Generated fixtures only - no personal documents, no network."""
import sys
from pathlib import Path

import pymupdf
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_pdf(path: Path, pages: int = 3, label: str = "Page", size=(595, 842), rotate_first: int = 0) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        pg = doc.new_page(width=size[0], height=size[1])
        pg.insert_text((72, 100), f"{label} {i + 1}", fontsize=24)
    if rotate_first:
        doc[0].set_rotation(rotate_first)
    doc.set_metadata({"title": f"{label} title", "author": "Test Author"})
    doc.save(path)
    doc.close()
    return path


def page_texts(path: Path, password: str | None = None) -> list[str]:
    with pymupdf.open(path) as d:
        if d.needs_pass:
            assert d.authenticate(password)
        return [p.get_text().strip() for p in d]


@pytest.fixture
def pdf_factory(tmp_path):
    def _make(name="doc.pdf", **kw):
        return make_pdf(tmp_path / name, **kw)
    return _make


@pytest.fixture
def img_dir(tmp_path):
    d = tmp_path / "imgs"
    d.mkdir()
    # photo-like noise JPEG, transparent PNG, palette PNG, WebP, BMP, 2-frame TIFF
    import random
    random.seed(1)
    photo = Image.effect_noise((800, 600), 60).convert("RGB")
    photo.save(d / "photo.jpg", quality=95)
    rgba = Image.new("RGBA", (300, 200), (255, 0, 0, 0))
    for x in range(100, 200):
        for y in range(50, 150):
            rgba.putpixel((x, y), (0, 0, 255, 255))
    rgba.save(d / "alpha.png")
    Image.new("P", (120, 90), 3).save(d / "palette.png")
    photo.resize((400, 300)).save(d / "pic.webp", quality=95)
    photo.resize((200, 150)).save(d / "pic.bmp")
    frames = [Image.new("RGB", (100, 100), c) for c in ("red", "green")]
    frames[0].save(d / "multi.tif", save_all=True, append_images=frames[1:])
    (d / "broken.png").write_bytes(b"not an image at all")
    return d
