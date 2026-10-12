import hashlib

import pytest
from PIL import Image

from core.common import InvalidInputError
from core.image_compress import CompressOptions, compress_images, image_info


def _hash(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_jpeg_compress_smaller_and_source_untouched(tmp_path, img_dir):
    src = img_dir / "photo.jpg"
    before = _hash(src)
    res = compress_images([src], tmp_path / "out", CompressOptions(quality=40))
    o = res.details["outcomes"][0]
    assert o.output.parent == (tmp_path / "out").resolve() and o.output.name == "photo_compressed.jpg"
    assert o.new_size < o.original_size and o.percent_saved > 10
    assert o.output.stat().st_size == o.new_size                # reported size == real size
    assert _hash(src) == before                                   # original untouched
    assert image_info(o.output).format == "JPEG"


def test_resize_never_upscales_and_keeps_aspect(tmp_path, img_dir):
    res = compress_images([img_dir / "photo.jpg"], tmp_path, CompressOptions(max_width=400, max_height=400))
    assert res.details["outcomes"][0].new_dims == (400, 300)
    res = compress_images([img_dir / "photo.jpg"], tmp_path / "big", CompressOptions(max_width=5000, quality=95))
    assert res.details["outcomes"][0].new_dims == (800, 600)


def test_transparency_preserved_png_and_webp(tmp_path, img_dir):
    res = compress_images([img_dir / "alpha.png"], tmp_path / "a", CompressOptions(max_width=150))
    out = res.details["outcomes"][0].output
    with Image.open(out) as im:
        assert im.mode == "RGBA" and im.getpixel((2, 2))[3] == 0
    res = compress_images([img_dir / "alpha.png"], tmp_path / "w", CompressOptions(out_format="webp", quality=80))
    with Image.open(res.details["outcomes"][0].output) as im:
        assert im.format == "WEBP" and im.mode == "RGBA" and im.getpixel((2, 2))[3] == 0


def test_transparent_to_jpeg_flattens_on_white(tmp_path, img_dir):
    res = compress_images([img_dir / "alpha.png"], tmp_path, CompressOptions(out_format="jpeg", quality=90))
    with Image.open(res.details["outcomes"][0].output) as im:
        assert im.mode == "RGB" and min(im.getpixel((2, 2))) > 240


def test_webp_bmp_tiff_and_png_graphics(tmp_path, img_dir):
    files = [img_dir / n for n in ("pic.webp", "pic.bmp", "multi.tif", "palette.png")]
    res = compress_images(files, tmp_path / "o", CompressOptions(quality=50))
    by = {o.source.name: o for o in res.details["outcomes"]}
    assert by["pic.bmp"].output.suffix == ".png" and "PNG" in by["pic.bmp"].note
    assert by["pic.bmp"].new_size < by["pic.bmp"].original_size
    assert by["multi.tif"].output is None or "first frame" in by["multi.tif"].note


def test_already_optimal_is_skipped_not_inflated(tmp_path, img_dir):
    first = compress_images([img_dir / "photo.jpg"], tmp_path / "a", CompressOptions(quality=30))
    again = compress_images([first.details["outcomes"][0].output], tmp_path / "b", CompressOptions(quality=95))
    o = again.details["outcomes"][0]
    assert o.skipped and o.output is None
    assert list((tmp_path / "b").iterdir()) == []                  # nothing written, no temp files left
    assert any("already well compressed" in w for w in again.warnings)


def test_batch_continues_after_invalid_image(tmp_path, img_dir):
    res = compress_images([img_dir / "broken.png", img_dir / "photo.jpg"], tmp_path / "o", CompressOptions(quality=50))
    assert len(res.outputs) == 1
    assert any("broken.png" in w for w in res.warnings)
    with pytest.raises(InvalidInputError):
        compress_images([img_dir / "broken.png"], tmp_path / "o2")
    with pytest.raises(InvalidInputError):
        compress_images([], tmp_path / "o3")
    with pytest.raises(InvalidInputError):
        compress_images([img_dir / "photo.jpg"], tmp_path / "o4", CompressOptions(quality=0))


def test_overwrite_mode_only_replaces_when_smaller(tmp_path, img_dir):
    import shutil
    work = tmp_path / "w"
    shutil.copytree(img_dir, work)
    src = work / "photo.jpg"
    size = src.stat().st_size
    res = compress_images([src], None, CompressOptions(quality=40, overwrite_originals=True))
    assert src.stat().st_size < size and res.details["outcomes"][0].output == src
    assert not list(work.glob(".*tmp*"))                            # no temp files left behind
