import pymupdf
import pytest

from core.common import (InvalidInputError, OperationCancelled, JobContext, OutputExistsError, parse_ranges,
                         ranges_to_pages, pages_to_spec)
from core.pdf_extract_pages import extract_pages
from core.pdf_merge import merge_pdfs
from core.pdf_organize import PagePlan, organize_pdf
from core.pdf_remove_pages import remove_pages
from core.pdf_split import split_pdf
from core.pdf_compress import compress_pdf
from conftest import make_pdf, page_texts


# ---------------------------------------------------------------- range parsing
def test_parse_ranges_ok():
    assert parse_ranges("1-3, 5, 8-10", 10) == [(1, 3), (5, 5), (8, 10)]
    assert ranges_to_pages([(1, 3), (2, 4)]) == [0, 1, 2, 3]
    assert ranges_to_pages([(3, 3), (1, 1)], keep_order=True) == [2, 0]
    assert pages_to_spec([0, 1, 2, 4]) == "1-3, 5"


@pytest.mark.parametrize("bad", ["", "  ", "0", "abc", "3-1", "1-99", "1,,x", "-2", "1-2-3"])
def test_parse_ranges_invalid(bad):
    with pytest.raises(InvalidInputError):
        parse_ranges(bad, 10)


# ----------------------------------------------------------------------- merge
def test_merge_order_and_metadata(tmp_path, pdf_factory):
    a = pdf_factory("a.pdf", pages=2, label="A")
    b = pdf_factory("b.pdf", pages=1, label="B")
    c = pdf_factory("c.pdf", pages=2, label="C", size=(300, 400))
    out = tmp_path / "m.pdf"
    res = merge_pdfs([c, a, b], out)
    assert page_texts(out) == ["C 1", "C 2", "A 1", "A 2", "B 1"]
    with pymupdf.open(out) as d:
        assert d[0].rect.width == 300 and d[2].rect.width == 595  # different page sizes preserved
        assert d.metadata["title"] == "C title"
    assert res.details["pages"] == 5


def test_merge_needs_two_and_corrupt_and_empty(tmp_path, pdf_factory):
    a = pdf_factory("a.pdf")
    with pytest.raises(InvalidInputError):
        merge_pdfs([a], tmp_path / "x.pdf")
    with pytest.raises(InvalidInputError):
        merge_pdfs([], tmp_path / "x.pdf")
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 this is not really a pdf")
    with pytest.raises(InvalidInputError, match="damaged"):
        merge_pdfs([a, bad], tmp_path / "x.pdf")
    notpdf = tmp_path / "t.pdf"
    notpdf.write_text("hello")
    with pytest.raises(InvalidInputError, match="not a PDF"):
        merge_pdfs([a, notpdf], tmp_path / "x.pdf")
    empty = tmp_path / "e.pdf"
    empty.touch()
    with pytest.raises(InvalidInputError, match="empty"):
        merge_pdfs([a, empty], tmp_path / "x.pdf")
    assert not (tmp_path / "x.pdf").exists()  # a failed run leaves no output and no temp files
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp.pdf")]


def test_output_exists_requires_overwrite(tmp_path, pdf_factory):
    a, b = pdf_factory("a.pdf"), pdf_factory("b.pdf")
    out = tmp_path / "m.pdf"
    merge_pdfs([a, b], out)
    with pytest.raises(OutputExistsError):
        merge_pdfs([a, b], out)
    merge_pdfs([a, b], out, overwrite=True)
    assert len(page_texts(out)) == 6


# ----------------------------------------------------------------------- split
def test_split_every_page(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=3)
    res = split_pdf(src, tmp_path / "out", mode="pages")
    assert [p.name for p in res.outputs] == ["doc_page_001.pdf", "doc_page_002.pdf", "doc_page_003.pdf"]
    assert page_texts(res.outputs[1]) == ["Page 2"]


def test_split_ranges_and_every_n(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=10)
    res = split_pdf(src, tmp_path / "r", mode="ranges", ranges_spec="1-3, 5, 8-10")
    assert [len(page_texts(p)) for p in res.outputs] == [3, 1, 3]
    assert page_texts(res.outputs[2]) == ["Page 8", "Page 9", "Page 10"]
    res = split_pdf(src, tmp_path / "n", mode="every", every_n=4)
    assert [len(page_texts(p)) for p in res.outputs] == [4, 4, 2]


def test_split_invalid_and_collision(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=3)
    with pytest.raises(InvalidInputError):
        split_pdf(src, tmp_path / "o", mode="ranges", ranges_spec="2-9")
    with pytest.raises(InvalidInputError):
        split_pdf(src, tmp_path / "o", mode="every", every_n=0)
    split_pdf(src, tmp_path / "o", mode="pages")
    with pytest.raises(OutputExistsError):
        split_pdf(src, tmp_path / "o", mode="pages")


# --------------------------------------------------------------- remove / extract
def test_remove_pages(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=6)
    out = tmp_path / "r.pdf"
    res = remove_pages(src, out, "2, 4-5")
    assert page_texts(out) == ["Page 1", "Page 3", "Page 6"]
    assert len(page_texts(src)) == 6  # original untouched
    assert pymupdf.open(out).metadata["author"] == "Test Author"
    assert res.details["removed"] == 3


def test_remove_all_pages_rejected(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=2)
    with pytest.raises(InvalidInputError, match="every page"):
        remove_pages(src, tmp_path / "r.pdf", "1-2")


def test_remove_in_place_needs_confirmation(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=3)
    with pytest.raises(OutputExistsError):
        remove_pages(src, src, "1")
    remove_pages(src, src, "1", overwrite=True)  # explicit confirmation
    assert page_texts(src) == ["Page 2", "Page 3"]


def test_extract_pages_orders(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=6)
    out = tmp_path / "e.pdf"
    extract_pages(src, out, "5, 1-2")
    assert page_texts(out) == ["Page 1", "Page 2", "Page 5"]  # document order by default
    out2 = tmp_path / "e2.pdf"
    extract_pages(src, out2, "5, 1-2", custom_order=True)
    assert page_texts(out2) == ["Page 5", "Page 1", "Page 2"]
    with pytest.raises(InvalidInputError):
        extract_pages(src, tmp_path / "e3.pdf", "7")


# --------------------------------------------------------------------- organize
def test_organize_reorder_rotate_duplicate_delete(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=4, rotate_first=90)
    out = tmp_path / "o.pdf"
    plan = [PagePlan(2), PagePlan(0, 90), PagePlan(0), PagePlan(3, 270)]  # page 2 (index 1) deleted
    organize_pdf(src, out, plan)
    assert page_texts(out) == ["Page 3", "Page 1", "Page 1", "Page 4"]
    with pymupdf.open(out) as d:
        assert [p.rotation for p in d] == [0, 180, 90, 270]  # existing rotation respected, extra added
    with pytest.raises(InvalidInputError):
        organize_pdf(src, tmp_path / "o2.pdf", [])
    with pytest.raises(InvalidInputError):
        organize_pdf(src, tmp_path / "o3.pdf", [PagePlan(9)])
    with pytest.raises(InvalidInputError):
        organize_pdf(src, tmp_path / "o4.pdf", [PagePlan(0, 45)])


# ---------------------------------------------------------------------- compress
def _pdf_with_big_image(path):
    from PIL import Image
    import io
    im = Image.effect_noise((1600, 1600), 80).convert("RGB")
    buf = io.BytesIO()
    im.save(buf, "PNG")  # lossless, large
    doc = pymupdf.open()
    pg = doc.new_page()
    pg.insert_image(pymupdf.Rect(36, 36, 300, 300), stream=buf.getvalue())  # ~ 400 dpi
    pg.insert_text((72, 400), "Vector and text stay", fontsize=16)
    doc.save(path)
    return path


def test_compress_presets_reduce_image_pdf_and_keep_text(tmp_path):
    src = _pdf_with_big_image(tmp_path / "big.pdf")
    sizes = {}
    for preset in ("low", "medium", "high"):
        out = tmp_path / f"{preset}.pdf"
        res = compress_pdf(src, out, preset)
        sizes[preset] = out.stat().st_size
        assert page_texts(out) == ["Vector and text stay"]  # text preserved, not rasterised
        assert res.details["before"] == src.stat().st_size
    assert sizes["medium"] < src.stat().st_size
    assert sizes["high"] <= sizes["medium"]


def test_compress_reports_honestly_when_not_smaller(tmp_path, pdf_factory):
    src = pdf_factory("tiny.pdf", pages=1)
    res = compress_pdf(src, tmp_path / "t.pdf", "low")
    assert "after" in res.details and isinstance(res.details["reduced"], bool)
    if not res.details["reduced"]:
        assert "could not be made smaller" in res.message


# ---------------------------------------------------------------- cancel / safety
def test_cancellation_stops_and_cleans_up(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=5)
    ctx = JobContext()
    ctx.progress = lambda d, t, m: ctx.cancel.cancel() if d == 2 else None
    with pytest.raises(OperationCancelled):
        split_pdf(src, tmp_path / "o", mode="pages", ctx=ctx)
    assert not [p for p in (tmp_path / "o").iterdir() if p.name.startswith(".")]  # no temp leftovers


def test_merge_combines_bookmarks_with_page_offsets(tmp_path):
    def with_toc(name, titles):
        p = make_pdf(tmp_path / name, 2, name[0].upper())
        with pymupdf.open(p) as d:
            d.set_toc([[1, titles[0], 1], [1, titles[1], 2]])
            d.saveIncr()
        return p
    a, b = with_toc("a.pdf", ["A-one", "A-two"]), with_toc("b.pdf", ["B-one", "B-two"])
    res = merge_pdfs([a, b], tmp_path / "m.pdf")
    with pymupdf.open(tmp_path / "m.pdf") as d:
        assert d.get_toc() == [[1, "A-one", 1], [1, "A-two", 2], [1, "B-one", 3], [1, "B-two", 4]]
    assert any("bookmarks" in w for w in res.warnings)  # advisory still shown for the sources
