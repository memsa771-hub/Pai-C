"""Slice 6a Task 1: the renderer's library gives byte-identical PDFs for the same input (spec S6a-D9)."""

import io


def _page() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    out = io.BytesIO()
    c = canvas.Canvas(out, pagesize=A4, invariant=1)
    c.setFont("Helvetica", 12)
    c.drawString(72, 760, "SAMPLE - TEST DOCUMENT")
    c.showPage()
    c.save()
    return out.getvalue()


def test_reportlab_invariant_is_byte_identical():
    first, second = _page(), _page()
    assert first.startswith(b"%PDF-") and first == second
