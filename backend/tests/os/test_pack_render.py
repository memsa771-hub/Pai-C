"""Slice 6a Task 6: the pack renderer and document conversion (spec S6a-D3, D9). Synthetic files made here only."""

import io
import os
import time

import pypdfium2
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter

from app.os.packs.config import Format
from app.os.packs.datasheet import SheetRow
from app.os.packs.render import MAX_PAGES, Unfixable, convert_document, filename, render_sheet, render_statement

ROWS = [SheetRow("Personal details", "surname", "Surname", "KHAN", "document", 1, False),
        SheetRow("Personal details", "email", "Email", None, None, None, True),
        SheetRow("Contact", "phone", "Phone", "+00 000 0000", "entered", None, False)]
SOP = "I want to study data science.\n\n" + "A long paragraph of fictional text. " * 200


def jpeg(w: int, h: int, exif_orientation: int | None = None, noise: bool = False) -> bytes:
    img = Image.frombytes("RGB", (w, h), os.urandom(w * h * 3)) if noise else Image.new("RGB", (w, h), (240, 240, 230))
    if not noise:
        d = ImageDraw.Draw(img)
        d.rectangle((0, 0, w // 2, h // 10), fill=(20, 20, 20))  # a dark band at the top-left
    out = io.BytesIO()
    kwargs = {"quality": 90}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs["exif"] = exif
    img.save(out, "JPEG", **kwargs)
    return out.getvalue()


def blank_pdf(pages: int) -> bytes:
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=595, height=842)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def page_size(pdf: bytes) -> tuple[float, float]:
    doc = pypdfium2.PdfDocument(pdf)
    try:
        return doc[0].get_size()
    finally:
        doc.close()


def test_sheet_render_deterministic():
    a, b = render_sheet(ROWS, "Data sheet: MSc Example"), render_sheet(ROWS, "Data sheet: MSc Example")
    assert a.startswith(b"%PDF-") and a == b
    assert len(PdfReader(io.BytesIO(a)).pages) == 1


def test_statement_render_deterministic():
    a, b = render_statement(SOP, "Statement of purpose"), render_statement(SOP, "Statement of purpose")
    assert a == b and len(PdfReader(io.BytesIO(a)).pages) >= 2  # long text wraps onto more pages


def test_changed_input_new_bytes():
    assert render_statement(SOP, "SOP") != render_statement(SOP + " One more sentence.", "SOP")
    changed = [*ROWS[:2], SheetRow("Contact", "phone", "Phone", "+00 000 0001", "entered", None, False)]
    assert render_sheet(ROWS, "t") != render_sheet(changed, "t")


def test_large_rotated_photo_under_limit():
    """Review Focus: a huge phone photo, EXIF-rotated, comes out upright, as one PDF page, within the limit."""
    data = jpeg(8000, 6000, exif_orientation=6)
    got = convert_document(data, "jpeg", Format(max_mb=2))
    assert not isinstance(got, Unfixable)
    pdf, pages = got
    assert pages == 1 and len(pdf) <= 2 * 1024 * 1024
    w, h = page_size(pdf)
    assert h > w  # landscape pixels + orientation 6 = portrait
    assert convert_document(data, "jpeg", Format(max_mb=2)) == got  # deterministic


def test_small_pdf_passes_through():
    pdf = blank_pdf(2)
    assert convert_document(pdf, "pdf", Format(max_mb=5)) == (pdf, 2)


def test_unshrinkable_scan():
    got = convert_document(jpeg(2000, 2000, noise=True), "jpeg", Format(max_mb=0.05))
    assert isinstance(got, Unfixable) and "smaller than" in got.reason


def test_original_untouched():
    data = jpeg(3000, 2000)
    copy = bytes(data)
    convert_document(data, "jpeg", Format(max_mb=0.2))
    assert data == copy


def test_page_cap():
    """Review Focus: a 60-page scan is refused quickly, without rendering every page."""
    started = time.monotonic()
    got = convert_document(blank_pdf(60), "pdf", Format(max_mb=0.001))
    assert isinstance(got, Unfixable) and got.reason == f"too many pages (60); the limit is {MAX_PAGES}"
    assert time.monotonic() - started < 20


def test_damaged_file():
    for data, kind in ((b"%PDF-1.4 not really a pdf", "pdf"), (b"\xff\xd8\xff not really a jpeg", "jpeg")):
        got = convert_document(data, kind, Format(max_mb=5))
        assert isinstance(got, Unfixable) and got.reason == "upload a clearer copy"


def test_filename():
    assert filename("min_passing_grade", "Minimum passing grade letter") == "minimum-passing-grade-letter.pdf"
    assert filename("added:1", "Módule déscriptions / 2024!") == "module-descriptions-2024.pdf"
