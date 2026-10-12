import pymupdf
import pytest

from core.common import InvalidInputError, PasswordRequiredError, WrongPasswordError
from core.pdf_extract_pages import extract_pages
from core.pdf_merge import merge_pdfs
from core.pdf_security import protect_pdf, unlock_pdf
from core.pdf_to_image import pdf_to_images
from conftest import page_texts


def test_protect_then_open_with_password(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=2)
    out = tmp_path / "p.pdf"
    res = protect_pdf(src, out, "s3cret", "owner!")
    with pymupdf.open(out) as d:
        assert d.needs_pass
        assert d.authenticate("wrong") == 0
    with pymupdf.open(out) as d:
        assert d.authenticate("s3cret") == 2
        assert d.metadata["encryption"] and "AES" in d.metadata["encryption"] and "256" in d.metadata["encryption"]
    assert page_texts(out, "s3cret") == ["Page 1", "Page 2"]
    assert any("screenshots" in w for w in res.warnings)  # limits of permissions are stated


def test_protect_requires_password_and_unprotected_input(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf")
    with pytest.raises(InvalidInputError):
        protect_pdf(src, tmp_path / "p.pdf", "")
    enc = tmp_path / "enc.pdf"
    protect_pdf(src, enc, "pw")
    with pytest.raises(PasswordRequiredError, match="Unlock"):  # already protected: point the user to Unlock
        protect_pdf(enc, tmp_path / "again.pdf", "pw2")


def test_permissions_applied(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf")
    out = tmp_path / "p.pdf"
    protect_pdf(src, out, "u", "o", allow_print=False, allow_copy=False)
    with pymupdf.open(out) as d:
        d.authenticate("u")
        assert not d.permissions & pymupdf.PDF_PERM_COPY
        assert not d.permissions & pymupdf.PDF_PERM_PRINT


def test_unlock_correct_and_wrong_password(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf", pages=2)
    enc = tmp_path / "enc.pdf"
    protect_pdf(src, enc, "pw", "own")
    with pytest.raises(WrongPasswordError):
        unlock_pdf(enc, tmp_path / "u.pdf", "nope")
    assert not (tmp_path / "u.pdf").exists()
    with pytest.raises(PasswordRequiredError):
        unlock_pdf(enc, tmp_path / "u.pdf", "")
    unlock_pdf(enc, tmp_path / "u.pdf", "pw")
    with pymupdf.open(tmp_path / "u.pdf") as d:
        assert not d.needs_pass and not d.is_encrypted
    assert page_texts(tmp_path / "u.pdf") == ["Page 1", "Page 2"]


def test_unlock_permission_only_needs_owner_password(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf")
    perm = tmp_path / "perm.pdf"
    d = pymupdf.open(src)
    d.save(perm, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="", owner_pw="own",
           permissions=pymupdf.PDF_PERM_ACCESSIBILITY)
    d.close()
    with pytest.raises(WrongPasswordError):
        unlock_pdf(perm, tmp_path / "u.pdf", "guess")
    unlock_pdf(perm, tmp_path / "u.pdf", "own")
    with pymupdf.open(tmp_path / "u.pdf") as chk:
        assert chk.permissions in (-1,) or chk.permissions & pymupdf.PDF_PERM_COPY


def test_unlock_rejects_unprotected(tmp_path, pdf_factory):
    with pytest.raises(InvalidInputError, match="nothing to unlock"):
        unlock_pdf(pdf_factory("doc.pdf"), tmp_path / "u.pdf", "x")


def test_protected_files_never_silently_treated_as_unlocked(tmp_path, pdf_factory):
    src = pdf_factory("doc.pdf")
    enc = tmp_path / "enc.pdf"
    protect_pdf(src, enc, "pw")
    other = pdf_factory("o.pdf")
    with pytest.raises(PasswordRequiredError):          # tools that read pages ask for a password
        pdf_to_images(enc, tmp_path / "img")
    with pytest.raises(WrongPasswordError):
        pdf_to_images(enc, tmp_path / "img", password="bad")
    with pytest.raises(PasswordRequiredError):
        merge_pdfs([enc, other], tmp_path / "m.pdf")    # modifying tools refuse; never output an unprotected copy
    with pytest.raises(PasswordRequiredError):
        extract_pages(enc, tmp_path / "e.pdf", "1")
    assert not (tmp_path / "m.pdf").exists() and not (tmp_path / "e.pdf").exists()
    res = pdf_to_images(enc, tmp_path / "img", password="pw")
    assert len(res.outputs) == 3  # the fixture has 3 pages


def test_password_not_in_error_messages_or_logs(tmp_path, pdf_factory, caplog):
    src = pdf_factory("doc.pdf")
    enc = tmp_path / "enc.pdf"
    protect_pdf(src, enc, "TopSecret123")
    with caplog.at_level("DEBUG"):
        with pytest.raises(WrongPasswordError) as ei:
            unlock_pdf(enc, tmp_path / "u.pdf", "WrongGuess456")
    assert "WrongGuess456" not in str(ei.value) and "TopSecret123" not in caplog.text
    assert "WrongGuess456" not in caplog.text
