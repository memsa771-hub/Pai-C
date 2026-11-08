"""P2-T4: the ScanText port and its adapters (P2-D13; R-29). No real OCR runs unless an engine is installed."""

import hashlib
import stat
import sys

import pypdfium2 as pdfium
import pytest

from app.os.knowledge.research.scan import (
    DoclingScanText,
    FixedScanText,
    ScanFailed,
    TesseractScanText,
    default_languages,
    rasterise_pdf,
    scan_document,
)
from tests.os import scan_fixtures as fx

pytestmark = pytest.mark.req("R-29")


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def test_rasterise_gives_one_png_per_page_up_to_the_cap():
    pdf = fx.scan_pdf(fx.EN_LINES)
    pages = rasterise_pdf(pdf, 5)
    assert len(pages) == 1 and pages[0][:8] == b"\x89PNG\r\n\x1a\n"
    assert rasterise_pdf(pdf, 0) == []
    with pytest.raises(pdfium.PdfiumError):
        rasterise_pdf(b"not a pdf", 1)


def test_scan_document_image_and_pdf_through_a_fake_engine():
    png = fx.text_png(fx.EN_LINES)
    pdf = fx.scan_pdf(fx.EN_LINES)
    engine = FixedScanText("Applications close on 1 August 2027.")
    assert scan_document(engine, png, "image/png").text == "Applications close on 1 August 2027."
    assert scan_document(engine, pdf, "application/pdf").engine == "fixed"
    assert len(engine.calls) == 2


def test_scan_document_refuses_other_types_and_empty_results():
    engine = FixedScanText("")
    with pytest.raises(ScanFailed, match="no text"):
        scan_document(engine, fx.text_png(fx.EN_LINES), "image/png")
    with pytest.raises(ScanFailed, match="scannable"):
        scan_document(engine, b"x", "text/html")
    with pytest.raises(ScanFailed, match="rasterise"):
        scan_document(engine, b"broken", "application/pdf")


def test_fixed_engine_can_fail_on_one_image():
    png = fx.text_png(fx.EN_LINES)
    engine = FixedScanText({}, fail_on=[_sha(png)])
    with pytest.raises(ScanFailed):
        engine.scan(png)


def test_default_languages_come_from_data():
    assert default_languages() == ("en", "ur")


def _fake_tesseract(tmp_path, body: str):
    script = tmp_path / "tesseract"
    script.write_text(f"#!{sys.executable}\nimport sys\n{body}\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_tesseract_adapter_builds_the_command_and_reads_stdout(tmp_path):
    cmd = _fake_tesseract(tmp_path, "print(' '.join(sys.argv[2:]) + ' | page text')")
    engine = TesseractScanText(cmd)
    assert engine.available()
    result = engine.scan(b"image", languages=("en", "ur"))
    assert result.engine == "tesseract"
    assert result.text.endswith("stdout -l eng+urd | page text")
    assert "-l eng " in engine.scan(b"image", languages=("en",)).text + " "


def test_tesseract_adapter_failures_are_scan_failed(tmp_path):
    assert not TesseractScanText("no-such-tesseract-command").available()
    with pytest.raises(ScanFailed):
        TesseractScanText("no-such-tesseract-command").scan(b"x")
    bad = TesseractScanText(_fake_tesseract(tmp_path, "sys.exit(3)"))
    with pytest.raises(ScanFailed, match="exited 3"):
        bad.scan(b"x")
    with pytest.raises(ScanFailed, match="no code"):
        TesseractScanText(_fake_tesseract(tmp_path, "print('x')")).scan(b"x", languages=("xx",))


@pytest.mark.skipif(not TesseractScanText().available(), reason="tesseract is not installed")
def test_real_tesseract_reads_an_english_scan():
    from app.os.knowledge.research.text import normalise

    got = TesseractScanText().scan(fx.text_png(fx.EN_LINES), languages=("en",))
    assert normalise("Applications close on 1 August 2027.") in normalise(got.text)


@pytest.mark.skipif(not DoclingScanText().available(), reason="docling is not installed")
def test_real_docling_reads_an_english_scan():
    from app.os.knowledge.research.text import normalise

    got = DoclingScanText().scan(fx.text_png(fx.EN_LINES), languages=("en",))
    assert normalise("Applications close on 1 August 2027.") in normalise(got.text)


def test_docling_adapter_reports_unavailable_without_the_package():
    if DoclingScanText().available():
        pytest.skip("docling is installed")
    assert not DoclingScanText().available()
    with pytest.raises(ScanFailed):
        DoclingScanText().scan(b"x")


def test_a_page_over_the_pixel_cap_is_refused_before_it_is_drawn():
    pdf = fx.scan_pdf(fx.EN_LINES)
    with pytest.raises(ScanFailed, match="over the limit"):
        rasterise_pdf(pdf, 5, max_pixels=1000)
    assert len(rasterise_pdf(pdf, 5, max_pixels=25_000_000)) == 1
    engine = FixedScanText("text")
    with pytest.raises(ScanFailed, match="over the limit"):
        scan_document(engine, pdf, "application/pdf", max_pixels=1000)
    with pytest.raises(ScanFailed, match="over the limit"):
        scan_document(engine, fx.text_png(fx.EN_LINES), "image/png", max_pixels=1000)  # image files too
    with pytest.raises(ScanFailed, match="image"):
        scan_document(engine, b"not an image", "image/png")
    assert engine.calls == []


def test_tesseract_runs_with_one_thread_and_the_set_timeout(tmp_path):
    cmd = _fake_tesseract(tmp_path, "import os; print(os.environ.get('OMP_THREAD_LIMIT'))")
    assert TesseractScanText(cmd).scan(b"x").text == "1"
    assert TesseractScanText().timeout_s == 180.0
    slow = _fake_tesseract(tmp_path, "import time; time.sleep(5)")
    with pytest.raises(ScanFailed, match="TimeoutExpired"):
        TesseractScanText(slow, timeout_s=0.5).scan(b"x")
