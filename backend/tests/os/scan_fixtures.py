"""Fictional scans built from text inside the test (P2-T4): no image or PDF is committed.

`text_png` draws lines of text with PIL (RTL shaping through raqm for Urdu), `scan_pdf` wraps such an image in an
image-only PDF, `digital_pdf` is an ordinary PDF with a text layer. A font that lacks a glyph is never used: `font_for`
returns None and the Urdu tests skip on machines without a covering font.
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/freefont/FreeSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoNastaliqUrdu-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoNaskhArabic-Regular.ttf",
]
EN_LINES = ["Admissions notice", "Applications close on 1 August 2027.", "Fee per semester: 1000 units."]
UR_LINES = ["داخلے کی آخری تاریخ ۱ اگست ۲۰۲۷ ہے۔", "فیس فی سمسٹر ۱۰۰۰ یونٹ ہے۔"]  # fictional: dates and fees are invented


def raqm() -> bool:
    return features.check("raqm")


def font_for(text: str, size: int = 44) -> ImageFont.FreeTypeFont | None:
    """The first candidate font that has a glyph for every letter of `text`."""
    for path in FONT_CANDIDATES:
        if not Path(path).exists():
            continue
        font = ImageFont.truetype(path, size)
        missing = font.getmask("￿").getbbox()
        if all(c.isspace() or font.getmask(c).getbbox() != missing for c in set(text)):
            return font
    return None


def text_png(lines: list[str], *, rtl: bool = False, size: int = 44, noise: bool = False) -> bytes | None:
    """A white page with the lines in black; None when no font covers them."""
    font = font_for("".join(lines), size)
    if font is None or (rtl and not raqm()):
        return None
    pad, gap = 40, int(size * 1.6)
    width = max(int(font.getlength(line)) for line in lines) + 2 * pad
    img = Image.new("L", (width, pad * 2 + gap * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        y = pad + i * gap
        if rtl:
            draw.text((width - pad, y), line, font=font, fill=0, direction="rtl", language="ur", anchor="ra")
        else:
            draw.text((pad, y), line, font=font, fill=0)
    if noise:
        from PIL import ImageFilter

        img = img.filter(ImageFilter.GaussianBlur(2.5))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def scan_pdf(lines: list[str], *, rtl: bool = False) -> bytes | None:
    """An image-only PDF (a scan): no text layer."""
    png = text_png(lines, rtl=rtl)
    if png is None:
        return None
    buf = io.BytesIO()
    Image.open(io.BytesIO(png)).convert("RGB").save(buf, format="PDF")
    return buf.getvalue()


def digital_pdf(text: str) -> bytes:
    from tests.os.test_research_pages import minimal_pdf

    return minimal_pdf(text)
