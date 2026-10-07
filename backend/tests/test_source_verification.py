"""Recorded observations make research verification deterministic and offline."""

from datetime import datetime, timedelta, timezone

from app.plugins._shared.verification import SourceVerifier, official_url


NOW = datetime(2026, 10, 7, 12, tzinfo=timezone.utc)
SOURCE = "https://admissions.example.edu/programs/ms-cs"
OTHER = "https://www.example.edu/admissions/requirements"
CLAIM = {"kind": "requirement", "field": "test_attempt[IELTS].overall_score",
         "value": 7, "threshold": 7, "comparator": "gte", "unit": "IELTS band",
         "quote": "IELTS overall 7", "source_url": SOURCE,
         "checked_at": (NOW - timedelta(days=1)).isoformat()}


def _check(**changes):
    args = {"claims": [CLAIM], "source_url": SOURCE,
            "official_domains": {"example.edu"}, "intake": "fall 2027",
            "page_text": "Fall 2027: IELTS overall 7",
            "checked_at": NOW - timedelta(days=1),
            "corroboration": [{**CLAIM, "source_url": OTHER,
                               "checked_at": NOW.isoformat()}],
            "corroborated_at": NOW, "now": NOW}
    args.update(changes)
    return SourceVerifier().verify(**args)


def test_all_checks_pass_with_two_official_observations():
    verdict = _check()
    assert verdict.status == "verified"
    assert verdict.cycle_label == "2027"
    assert all(item["passed"] for item in verdict.checks.values())


def test_untrusted_or_lookalike_domains_never_verify():
    assert not official_url("https://example.edu.evil.test/admissions", {"example.edu"})
    assert not official_url("https://evil.test@www.example.edu/admissions", {"example.edu"})
    assert not official_url("http://www.example.edu/admissions", {"example.edu"})
    assert _check(official_domains={"other.edu"}).checks["official_source"]["passed"] is False


def test_old_cycle_and_invalid_schema_fail_separately():
    assert _check(page_text="Fall 2024 admission rules").checks["current_cycle"]["passed"] is False
    assert _check(claims=[{**CLAIM, "unit": None}]).checks["schema"]["passed"] is False
    assert _check(claims=[{**CLAIM, "kind": "fee", "value": "10000"}]).checks["schema"]["passed"] is False


def test_agreement_requires_matching_later_observation():
    assert _check(corroboration=[]).checks["agreement"]["passed"] is False
    assert _check(corroboration=[{**CLAIM, "value": 6,
                                  "source_url": OTHER}]).checks["agreement"]["passed"] is False
    assert _check(corroboration=[{**CLAIM, "source_url": "https://news.test/example"}]).checks["agreement"]["passed"] is False
    assert _check(corroborated_at=NOW - timedelta(days=2)).checks["agreement"]["passed"] is False


def test_freshness_tightens_near_deadline():
    old = NOW - timedelta(days=10)
    deadline = {"kind": "deadline", "field": "application.deadline",
                "value": "2026-11-01", "quote": "Apply by 1 November 2026",
                "source_url": SOURCE, "checked_at": old.isoformat()}
    verdict = _check(claims=[deadline], checked_at=old, corroboration=[])
    assert verdict.checks["freshness"]["passed"] is False
    assert _check(checked_at=NOW - timedelta(days=31)).checks["freshness"]["passed"] is False
