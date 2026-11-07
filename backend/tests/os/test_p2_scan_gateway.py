"""P2-T4: scans through the page gateway: `read_method: ocr`, language, the original kept (R-29, R-72). No real OCR."""

import os
from datetime import UTC, datetime

import pytest

from app.os.knowledge.research.pages import PageGateway
from app.os.knowledge.research.scan import FixedScanText
from app.os.knowledge.research.text import normalise
from app.os.knowledge.research.trust import quote_on_page
from app.os.knowledge.sources.allowlist import Scope, SourceDomains, load_allowlist
from app.os.knowledge.sources.suspect import SourceGuard
from app.os.settings import load_settings
from tests.os import scan_fixtures as fx

pytestmark = pytest.mark.req("R-29", "R-72")
ALPHA, OWN = "www.alpha-university.test", ["alpha-university.test"]
NOW = datetime(2027, 5, 2, 10, tzinfo=UTC)
EN = "Applications close on 1 August 2027."
SOURCES = os.path.join(os.path.dirname(__file__), "fixtures", "sources")


def gateway(engine, sites, scanner, *, guard=False):
    sources = None
    if guard:
        SourceDomains(engine, "pai").sync(load_allowlist(SOURCES))
        sources = SourceGuard(engine, "pai")
    return PageGateway(engine, "pai", load_settings({"DATABASE_URL": "x"}), client=sites.client(), clock=lambda: NOW,
                       sleep=lambda s: None, scanner=scanner, sources=sources)


def test_an_image_notice_is_read_by_the_scanner(engine, clean, fixture_sites):
    fixture_sites.set_page(ALPHA, "/notice.png", fx.text_png(fx.EN_LINES), "image/png")
    scanner = FixedScanText(EN)
    gw = gateway(engine, fixture_sites, scanner)
    page = gw.fetch(f"https://{ALPHA}/notice.png", OWN, [])
    assert page.ok and page.text == EN and page.read_method == "ocr" and page.language is None
    again = gw.fetch(f"https://{ALPHA}/notice.png", OWN, [])
    assert again.from_cache and again.read_method == "ocr" and len(scanner.calls) == 1  # the cache keeps how it was read


def test_without_a_scanner_an_image_is_refused_as_before(engine, clean, fixture_sites):
    fixture_sites.set_page(ALPHA, "/notice.png", fx.text_png(fx.EN_LINES), "image/png")
    page = gateway(engine, fixture_sites, None).fetch(f"https://{ALPHA}/notice.png", OWN, [])
    assert page.blocked == "unsupported:image/png" and page.read_method == "fetch"


def test_a_scanned_pdf_is_read_by_ocr_and_a_digital_pdf_is_not(engine, clean, fixture_sites):
    fixture_sites.set_page(ALPHA, "/scan.pdf", fx.scan_pdf(fx.EN_LINES), "application/pdf")
    fixture_sites.set_page(ALPHA, "/digital.pdf", fx.digital_pdf("Closing date is 1 August 2027, as published"),
                           "application/pdf")
    scanner = FixedScanText(EN)
    gw = gateway(engine, fixture_sites, scanner)
    scan = gw.fetch(f"https://{ALPHA}/scan.pdf", OWN, [])
    assert scan.ok and scan.read_method == "ocr" and scan.text == EN and len(scanner.calls) == 1
    digital = gw.fetch(f"https://{ALPHA}/digital.pdf", OWN, [])
    assert digital.ok and digital.read_method == "fetch" and len(scanner.calls) == 1  # no scan for a text layer


def test_a_failed_scan_is_not_readable_and_the_original_is_kept_for_the_checker(engine, clean, fixture_sites):
    png = fx.text_png(fx.EN_LINES)
    fixture_sites.set_page(ALPHA, "/notice.png", png, "image/png")
    gw = gateway(engine, fixture_sites, FixedScanText(""), guard=True)
    page = gw.fetch(f"https://{ALPHA}/notice.png", [], [], Scope(region="north_region", family="university"))
    assert page.blocked == "not_readable:ocr" and not page.ok
    snap = gw.sources.snapshots.get(page.snapshot_id)
    assert snap.flagged == "not_readable"
    assert gw.sources.snapshots.original(page.snapshot_id) == (png, "image/png")


def test_an_ocr_snapshot_records_ocr_language_and_original(engine, clean, fixture_sites):
    png = fx.text_png(fx.UR_LINES, rtl=True)
    if png is None:
        pytest.skip("no font with Urdu glyphs and raqm shaping")
    fixture_sites.set_page(ALPHA, "/notice.png", png, "image/png")
    gw = gateway(engine, fixture_sites, FixedScanText("\n".join(fx.UR_LINES)), guard=True)
    page = gw.fetch(f"https://{ALPHA}/notice.png", [], [], Scope(region="north_region", family="university"))
    assert page.ok and page.read_method == "ocr" and page.language == "ur"
    snap = gw.sources.snapshots.get(page.snapshot_id)
    assert (snap.read_method, snap.language) == ("ocr", "ur")
    assert gw.sources.snapshots.original(page.snapshot_id)[0] == png


def test_urdu_quote_in_another_letter_form_matches_the_scanned_page(engine, clean, fixture_sites):
    fixture_sites.set_page(ALPHA, "/notice.png", b"\x89PNG-fake", "image/png")
    gw = gateway(engine, fixture_sites, FixedScanText("\n".join(fx.UR_LINES)))
    page = gw.fetch(f"https://{ALPHA}/notice.png", OWN, [])
    assert page.language == "ur"
    assert quote_on_page("آخري تاريخ ١ اگست ٢٠٢٧", normalise(page.text))  # Arabic yeh, Arabic-Indic digits
    assert not quote_on_page("آخری تاریخ ۲ اگست ۲۰۲۷", normalise(page.text))
