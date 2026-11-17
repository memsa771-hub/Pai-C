"""P2-T4: the bake-off harness scores engines correctly (P2-D13). Fake engines only, plus any real one that is installed."""

import pytest

from app.os.knowledge.research.bakeoff import run_bakeoff, summarise, winner
from app.os.knowledge.research.scan import (
    DoclingScanText,
    FixedScanText,
    ScanFailed,
    ScanResult,
    TesseractScanText,
)
from tests.os import scan_fixtures as fx

pytestmark = pytest.mark.req("R-29")


class Garbling:
    """Reads everything but swaps a digit, so a quote with a date no longer matches."""
    name = "garbling"

    def available(self):
        return True

    def scan(self, image, *, languages=()):
        return ScanResult("\n".join(fx.EN_LINES + fx.UR_LINES).replace("1 August", "7 August").replace("۱", "۷"), self.name)


class Broken:
    name = "broken"

    def available(self):
        return True

    def scan(self, image, *, languages=()):
        raise ScanFailed("crash")


class Perfect:
    name = "perfect"

    def available(self):
        return True

    def scan(self, image, *, languages=()):
        return ScanResult("\n".join(fx.EN_LINES + fx.UR_LINES), self.name)


class Missing:
    name = "missing"

    def available(self):
        return False

    def scan(self, image, *, languages=()):
        raise AssertionError("must not run")


def test_cases_are_built_from_text_in_memory():
    cases = fx.bakeoff_cases()
    assert {"en_notice_png", "en_notice_pdf", "en_blurred_png"} <= {c.name for c in cases}
    assert all(c.data and c.quotes for c in cases)


def test_scores_winner_and_not_run():
    cases = fx.bakeoff_cases()
    scores = run_bakeoff([Perfect(), Garbling(), Broken(), Missing()], cases)
    summary = summarise(scores)
    assert summary["perfect"]["quote_pass_rate"] == 1.0 and summary["perfect"]["failures"] == 0
    assert summary["garbling"]["quote_pass_rate"] < 1.0
    assert summary["broken"]["failures"] == len(cases) and summary["broken"]["quote_pass_rate"] == 0.0
    assert summary["missing"]["ran"] == 0 and summary["missing"]["quote_pass_rate"] is None
    assert winner(summary) == "perfect"
    assert winner({k: v for k, v in summary.items() if k != "perfect"}) is None  # nobody passes every quote


def test_no_installed_engine_means_no_winner():
    summary = summarise(run_bakeoff([Missing()], fx.bakeoff_cases()))
    assert winner(summary) is None


def test_the_fixed_fake_engine_is_scored_through_the_same_path():
    summary = summarise(run_bakeoff([FixedScanText("\n".join(fx.EN_LINES))], [c for c in fx.bakeoff_cases() if c.language == "en"]))
    assert summary["fixed"]["quote_pass_rate"] == 1.0


@pytest.mark.skipif(not (TesseractScanText().available() or DoclingScanText().available()),
                    reason="no real OCR engine installed: the bake-off cannot compare real engines here")
def test_installed_engines_are_compared_on_the_fixtures():
    summary = summarise(run_bakeoff([TesseractScanText(), DoclingScanText()], fx.bakeoff_cases()))
    ran = [e for e, s in summary.items() if s["ran"]]
    assert ran and all(summary[e]["cases"] == len(fx.bakeoff_cases()) for e in ran)
