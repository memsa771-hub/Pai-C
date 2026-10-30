"""Slice 3 Task 3: upload checks, page preparation and tiles (spec S3-D4, S3-D5). Synthetic files only."""

import io

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter

from app.os.documents.intake import (
    MAX_BYTES,
    MAX_SIDE,
    UploadError,
    check_upload,
    prepare,
    tiles,
)

LONG_TEXT = "Transcript of record. " * 15  # > 200 characters of text layer


def jpeg(w=1200, h=1600, color=(200, 200, 200), orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (w, h), color)
    img.paste((0, 0, 0), (0, 0, w // 2, h // 10))  # a dark band at the top-left, to see rotation
    out = io.BytesIO()
    exif = img.getexif()
    if orientation:
        exif[274] = orientation
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def png(w=800, h=600) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(out, "PNG")
    return out.getvalue()


def webp() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (400, 300), (10, 20, 30)).save(out, "WEBP")
    return out.getvalue()


def text_pdf(text: str = LONG_TEXT) -> bytes:
    """A one-page PDF with a real text layer, built by hand."""
    stream = f"BT /F1 9 Tf 20 800 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


def scanned_pdf() -> bytes:
    """A one-page PDF that is only an image (a scan): no text layer."""
    out = io.BytesIO()
    Image.new("RGB", (850, 1100), (240, 240, 240)).save(out, "PDF", resolution=100)
    return out.getvalue()


def mixed_pdf() -> bytes:
    w = PdfWriter()
    for part in (text_pdf(), scanned_pdf()):
        for page in PdfReader(io.BytesIO(part)).pages:
            w.add_page(page)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def image_of(part) -> Image.Image:
    return Image.open(io.BytesIO(part.image))


# --- upload checks -----------------------------------------------------------------------------------------


@pytest.mark.parametrize("make, kind", [(jpeg, "jpeg"), (png, "png"), (webp, "webp"), (text_pdf, "pdf")])
def test_kinds_by_magic_bytes(make, kind):
    assert check_upload("whatever.bin", make()) == kind


def test_magic_bytes_not_extension():
    assert check_upload("passport.jfif", png()) == "png"  # the name says JPEG; the bytes say PNG
    with pytest.raises(UploadError, match="not a supported"):
        check_upload("transcript.pdf", b"Hello, this is plain text, not a PDF at all.")


def test_too_big_refused():
    with pytest.raises(UploadError, match="too big"):
        check_upload("big.pdf", b"%PDF-1.4\n" + b"0" * MAX_BYTES)
    with pytest.raises(UploadError, match="empty"):
        check_upload("empty.png", b"")


# --- preparation ---------------------------------------------------------------------------------------------


def test_prepare_text_pdf():
    [page] = prepare(text_pdf(), "pdf")
    assert page.page == 1 and page.image is None and "Transcript of record." in page.text


def test_prepare_short_text_pdf_page_is_rendered():
    [page] = prepare(text_pdf("Name: S. Khan"), "pdf")  # a text layer under 200 characters: treat as a scan
    assert page.text is None and page.media_type == "image/jpeg" and image_of(page).size[0] > 0


def test_prepare_scanned_pdf_renders():
    [page] = prepare(scanned_pdf(), "pdf")
    assert page.text is None and page.image and max(image_of(page).size) <= MAX_SIDE


def test_prepare_mixed_pdf_pages():
    parts = prepare(mixed_pdf(), "pdf")
    assert [p.page for p in parts] == [1, 2]
    assert parts[0].text and parts[0].image is None
    assert parts[1].text is None and parts[1].image


def test_prepare_large_rotated_photo():
    # 6000 x 4500 landscape pixels, EXIF orientation 6 (rotate 90 degrees clockwise to view): upright is portrait
    [page] = prepare(jpeg(6000, 4500, orientation=6), "jpeg")
    img = image_of(page)
    assert max(img.size) <= MAX_SIDE and img.size[1] > img.size[0]  # upright: taller than wide
    assert img.getexif().get(274) in (None, 1)  # no orientation left to apply twice


def test_prepare_png_and_webp():
    for data, kind in ((png(), "png"), (webp(), "webp")):
        [page] = prepare(data, kind)
        assert page.media_type == "image/jpeg" and image_of(page).format == "JPEG"


def test_prepare_corrupt_file_raises_upload_error():
    with pytest.raises(UploadError, match="could not be read"):
        prepare(b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, "png")


# --- tiles ---------------------------------------------------------------------------------------------------


def test_tiles_geometry():
    page = prepare(jpeg(1000, 1200), "jpeg")[0].image  # height/width 1.2: 2 bands
    bands = [Image.open(io.BytesIO(b)) for b in tiles(page)]
    assert len(bands) == 2 and all(b.size[0] == 1000 for b in bands)
    total = Image.open(io.BytesIO(page)).size[1]
    assert bands[0].size[1] + bands[1].size[1] > total  # they overlap
    assert bands[0].size[1] + bands[1].size[1] <= total * 1.25  # by about 10% of a band, not more


def test_tall_page_gets_three_tiles():
    page = prepare(jpeg(800, 1600), "jpeg")[0].image  # height/width 2.0 > 1.6
    assert len(tiles(page)) == 3


def test_tiles_deterministic():
    page = prepare(jpeg(1000, 1200), "jpeg")[0].image
    assert tiles(page) == tiles(page)
