"""P1-T6 Task 4 (R-11): the student sentences for an escalation pause. Approved by the owner in chat (2026-11-06); the gate
still holds: an unapproved file is returned only in rehearsal (CONNECT_CONSENT_DRAFT)."""

import re
from unittest.mock import patch

import pytest
import yaml

from app.config import config
from app.pai_c.connect import escalation_texts as texts

pytestmark = pytest.mark.req("R-11")
FIVE = ("not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other")
RAW = yaml.safe_load(texts.TEXTS_PATH.read_text(encoding="utf-8"))


def test_file_is_approved_by_the_owner():
    assert RAW["approved"] is True and RAW["version"]
    with patch.object(config, "CONNECT_CONSENT_DRAFT", False):
        assert texts.text("other") == RAW["reasons"]["other"].strip() and texts.action() == RAW["action"].strip()


UNAPPROVED = {"approved": False}


@pytest.mark.parametrize("reason", FIVE)
def test_reason_text_null_until_approved(reason):
    with patch.object(config, "CONNECT_CONSENT_DRAFT", False), patch.dict(texts._RAW, UNAPPROVED):
        assert texts.text(reason) is None
    with patch.object(config, "CONNECT_CONSENT_DRAFT", True), patch.dict(texts._RAW, UNAPPROVED):
        assert texts.text(reason) == RAW["reasons"][reason].strip()


def test_action_null_until_approved():
    with patch.object(config, "CONNECT_CONSENT_DRAFT", False), patch.dict(texts._RAW, UNAPPROVED):
        assert texts.action() is None
    with patch.object(config, "CONNECT_CONSENT_DRAFT", True), patch.dict(texts._RAW, UNAPPROVED):
        assert texts.action() == RAW["action"].strip()


def test_approved_file_is_returned_without_the_draft_flag():
    with patch.object(config, "CONNECT_CONSENT_DRAFT", False), patch.dict(texts._RAW, {"approved": True}):
        assert texts.text("other") and texts.action()


def test_unknown_reason_has_no_text():
    with patch.object(config, "CONNECT_CONSENT_DRAFT", True):
        assert texts.text("route_not_possible") is None and texts.text("") is None


def test_every_reason_has_text():
    assert set(RAW["reasons"]) == set(FIVE) == set(texts.REASONS)
    assert all(isinstance(v, str) and v.strip() for v in RAW["reasons"].values()) and RAW["action"].strip()


def test_missing_reason_fails_at_load(tmp_path):
    broken = {**RAW, "reasons": {k: v for k, v in RAW["reasons"].items() if k != "other"}}
    (tmp_path / "t.yaml").write_text(yaml.safe_dump(broken))
    with patch.object(texts, "TEXTS_PATH", tmp_path / "t.yaml"), pytest.raises(ValueError, match="other"):
        texts._load()


def test_no_country_words_in_texts():
    """Plain English: no country, institution or date (the words and codes below are a coarse guard, not a list of
    what is allowed)."""
    blob = " ".join([*RAW["reasons"].values(), RAW["action"]])
    assert not re.search(r"\b(19|20)\d\d\b", blob) and not re.search(r"\b[A-Z]{2}\b", blob)
    for word in ("pakistan", "germany", "ireland", "england", "india", "university", "college", "january", "monday"):
        assert word not in blob.lower()
