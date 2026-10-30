"""Upload checks, page preparation and tiles (spec S3-D4, S3-D5).

The file's kind comes from its first bytes, never from its name. A PDF page with a usable text layer is read as text;
any other page is rendered to an image. Every image leaves here upright (EXIF applied), at most MAX_SIDE pixels on
its longest side, as a JPEG without metadata.
"""

import io
from dataclasses import dataclass
from typing import Literal

import pypdfium2
from PIL import Image, ImageOps

Kind = Literal["jpeg", "png", "webp", "pdf"]

MAX_BYTES = 10_000_000
MAX_SIDE = 2_000
TEXT_MIN_CHARS = 200
RENDER_DPI = 200
JPEG_QUALITY = 90
TILE_OVERLAP = 0.10
TALL_RATIO = 1.6


class UploadError(ValueError):
    """The file cannot be taken; the message is safe to show the student."""


@dataclass(frozen=True)
class PagePart:
    page: int  # 1-based
    text: str | None
    image: bytes | None
    media_type: str | None  # "image/jpeg" when image is set


def check_upload(filename: str, data: bytes) -> Kind:
    if not data:
        raise UploadError(f"{filename} is empty.")
    if len(data) > MAX_BYTES:
        raise UploadError(f"{filename} is too big: the limit is {MAX_BYTES // 1_000_000} MB.")
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"%PDF-"):
        return "pdf"
    raise UploadError(f"{filename} is not a supported file: upload a PDF, JPEG, PNG or WebP.")


def prepare(data: bytes, kind: Kind) -> list[PagePart]:
    try:
        if kind == "pdf":
            return _prepare_pdf(data)
        with Image.open(io.BytesIO(data)) as img:
            return [PagePart(1, None, _to_jpeg(ImageOps.exif_transpose(img)), "image/jpeg")]
    except UploadError:
        raise
    except Exception as e:  # pdfium and Pillow raise many types for a damaged file
        raise UploadError("The file could not be read: it may be damaged or password-protected.") from e


def _prepare_pdf(data: bytes) -> list[PagePart]:
    pdf = pypdfium2.PdfDocument(data)
    try:
        parts = []
        for i in range(len(pdf)):
            page = pdf[i]
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            textpage.close()
            if len(text.strip()) >= TEXT_MIN_CHARS:
                parts.append(PagePart(i + 1, text, None, None))
            else:
                img = page.render(scale=RENDER_DPI / 72).to_pil()
                parts.append(PagePart(i + 1, None, _to_jpeg(img), "image/jpeg"))
            page.close()
        return parts
    finally:
        pdf.close()


def _to_jpeg(img: Image.Image) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=JPEG_QUALITY)
    return out.getvalue()


def tiles(image: bytes) -> list[bytes]:
    """Horizontal bands of a prepared page, each overlapping the next by TILE_OVERLAP of a band."""
    with Image.open(io.BytesIO(image)) as img:
        w, h = img.size
        n = 3 if h / w > TALL_RATIO else 2
        band = h / (n - TILE_OVERLAP * (n - 1))
        step = band * (1 - TILE_OVERLAP)
        out = []
        for i in range(n):
            top = round(i * step)
            bottom = h if i == n - 1 else round(i * step + band)
            buf = io.BytesIO()
            img.crop((0, top, w, bottom)).convert("RGB").save(buf, "JPEG", quality=JPEG_QUALITY)
            out.append(buf.getvalue())
        return out
