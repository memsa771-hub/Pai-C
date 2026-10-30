"""The pack renderer (Slice 6a spec S6a-D3, D9): the data sheet and the approved statements as PDFs, and the student's
documents converted to the portal's format and size.

Deterministic: ReportLab runs in `invariant` mode (a fixed creation date and document ID), and images are resized and
encoded the same way every time, so the same inputs give byte-identical files and a rendered file traces back to its
inputs. The original upload is never changed. A file that cannot be made to fit comes back as `Unfixable` with a
reason the student can act on.
"""

import io
import re
import unicodedata
from dataclasses import dataclass

import pypdfium2
from PIL import Image, ImageOps
from pypdf import PdfReader
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfgen import canvas

from app.os.packs.config import Format

MAX_PAGES = 40
MAX_PIXELS = 100_000_000  # per page; guards memory (an 8000x6000 phone photo is 48 MP)
FLOOR_PX = 1_600  # long side below which a scan stops being legible
START_PX = 3_000  # long side the shrinking starts from
STEP = 0.85
JPEG_QUALITY = 85
RENDER_DPI = 150  # for a PDF that must be rasterised to shrink
MARGIN, FONT, SIZE, LEADING = 56, "Helvetica", 10, 14


@dataclass(frozen=True)
class Unfixable:
    reason: str


def _canvas(out: io.BytesIO, title: str) -> canvas.Canvas:
    c = canvas.Canvas(out, pagesize=A4, invariant=1)
    c.setTitle(title)
    c.setAuthor("")
    c.setCreator("")
    c.setProducer("")
    return c


def _latin(text: str) -> str:
    """The built-in fonts use WinAnsi (cp1252): Latin-1 plus smart quotes, dashes, bullets and currency signs.
    Anything else is replaced so the file still renders."""
    return text.encode("cp1252", "replace").decode("cp1252")


class _Writer:
    """Wrapped text onto A4 pages, a new page when one is full."""

    def __init__(self, c: canvas.Canvas) -> None:
        self.c, self.width = c, A4[0] - 2 * MARGIN
        self.y = A4[1] - MARGIN

    def line(self, text: str, font: str = FONT, size: int = SIZE, gap: int = 0) -> None:
        for part in simpleSplit(_latin(text), font, size, self.width) or [""]:
            if self.y < MARGIN:
                self.c.showPage()
                self.y = A4[1] - MARGIN
            self.c.setFont(font, size)
            self.c.drawString(MARGIN, self.y, part)
            self.y -= LEADING
        self.y -= gap


def render_sheet(rows: list, title: str) -> bytes:
    """The data sheet: each section's fields with their values; a missing value says so."""
    out = io.BytesIO()
    c = _canvas(out, title)
    w = _Writer(c)
    w.line(title, "Helvetica-Bold", 14, gap=6)
    section = None
    for r in rows:
        if r.section != section:
            section = r.section
            w.line(section, "Helvetica-Bold", 11, gap=2)
        w.line(f"{r.label}: {r.value if r.value is not None else '(missing)'}")
    c.showPage()
    c.save()
    return out.getvalue()


def render_statement(text: str, title: str) -> bytes:
    """An approved statement as typed: its paragraphs, wrapped, nothing added or removed."""
    out = io.BytesIO()
    c = _canvas(out, title)
    w = _Writer(c)
    w.line(title, "Helvetica-Bold", 14, gap=6)
    for para in text.split("\n"):
        w.line(para, gap=2 if para.strip() else 0)
    c.showPage()
    c.save()
    return out.getvalue()


def _bounded_jpeg(img: Image.Image) -> bytes:
    """One page as a JPEG with its long side at most START_PX: what the shrinking starts from. Pages are kept encoded,
    so only one is decoded at a time."""
    img = img.convert("RGB")
    if max(img.size) > START_PX:
        scale = START_PX / max(img.size)
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=95)
    return buf.getvalue()


def _images_pdf(pages: list[bytes], long_side: int) -> bytes:
    out = io.BytesIO()
    c = canvas.Canvas(out, invariant=1)
    for page in pages:
        with Image.open(io.BytesIO(page)) as img:
            scale = min(1.0, long_side / max(img.size))
            small = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                               Image.Resampling.LANCZOS) if scale < 1 else img.copy()
        buf = io.BytesIO()
        small.save(buf, "JPEG", quality=JPEG_QUALITY)
        fit = min(A4[0] / small.width, A4[1] / small.height)  # the page has the image's shape, at most A4
        w, h = small.width * fit, small.height * fit
        c.setPageSize((w, h))
        c.drawImage(ImageReader(io.BytesIO(buf.getvalue())), 0, 0, w, h)
        c.showPage()
    c.save()
    return out.getvalue()


def _too_large(width: float, height: float) -> bool:
    return width * height > MAX_PIXELS


def _pdf_pages(data: bytes) -> list[bytes]:
    """Each page rendered at RENDER_DPI, but never more than START_PX on its long side (a page declared at pixel size
    would otherwise be metres wide), and encoded at once: one decoded page in memory at a time."""
    doc = pypdfium2.PdfDocument(data)
    try:
        pages = []
        for i in range(len(doc)):
            w, h = doc[i].get_size()
            scale = min(RENDER_DPI / 72, START_PX / max(w, h, 1))
            img = doc[i].render(scale=scale).to_pil()
            pages.append(_bounded_jpeg(img))
            img.close()
        return pages
    finally:
        doc.close()


def convert_document(data: bytes, kind: str, fmt: Format) -> tuple[bytes, int] | Unfixable:
    """The document as a PDF within `fmt.max_mb`, and its page count. A PDF already within the limit passes through
    unchanged; anything else is converted, shrinking image resolution down to FLOOR_PX on the long side."""
    limit = int(fmt.max_mb * 1024 * 1024)
    try:
        if kind == "pdf":
            pages = len(PdfReader(io.BytesIO(data)).pages)
            if pages == 0:
                return Unfixable("upload a clearer copy")
            if pages > MAX_PAGES:
                return Unfixable(f"too many pages ({pages}); the limit is {MAX_PAGES}")
            if len(data) <= limit:
                return data, pages
            pages = _pdf_pages(data)
        else:
            with Image.open(io.BytesIO(data)) as img:
                if _too_large(*img.size):
                    return Unfixable("page too large")
                pages = [_bounded_jpeg(ImageOps.exif_transpose(img))]
    except Exception:  # noqa: BLE001  (Pillow, pypdf and pdfium raise many types for a damaged file)
        return Unfixable("upload a clearer copy")
    longest = max(max(Image.open(io.BytesIO(p)).size) for p in pages)
    side, floor = min(longest, START_PX), min(FLOOR_PX, longest)
    while True:
        pdf = _images_pdf(pages, side)
        if len(pdf) <= limit:
            return pdf, len(pages)
        if side <= floor:
            return Unfixable(f"cannot make it smaller than {fmt.max_mb:g} MB without losing legibility; "
                             "upload a smaller scan")
        side = max(floor, int(side * STEP))


def filename(item_key: str, label: str) -> str:
    """A plain ASCII file name from the item's label (portals reject odd characters)."""
    def slug(s: str) -> str:
        ascii_text = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
        return re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")

    return (slug(label) or slug(item_key) or "document") + ".pdf"
