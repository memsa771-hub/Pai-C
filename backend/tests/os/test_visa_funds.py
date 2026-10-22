"""Slice 6b Task 2: the visa config and the funds calculator (spec S6b-D3, D4, D5, D7). Fictional values only."""

import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from app.os.documents.types import load_document_types
from app.os.eligibility.rules import profile_keys
from app.os.knowledge.port import Fact
from app.os.packs.checklist import checklist
from app.os.packs.config import PACK_DIR, PackConfigError, check_pack_config, load_pack_configs
from app.os.packs.funds import as_number, required_funds
from app.os.packs.inputs import DocState, PackInputs, ProfileValue
from app.os.playbooks import load_playbook_dir

TYPES = load_document_types()
BOOK = next(b for (k, _), b in load_playbook_dir().items() if k == "germany_master")
VISA = load_pack_configs(kind="visa")["germany_master"]
AT = datetime(2026, 10, 22, tzinfo=timezone.utc)
URL = "https://embassy.example/funds"


def fact(value, status="unconfirmed"):
    return Fact(value, "11.904,00 Euros yearly", URL, AT, 2027, status)


def inputs(**over) -> PackInputs:
    docs = {i.ref: DocState("confirmed", n, f"{n:064x}") for n, i in enumerate(VISA.checklist, 1) if i.kind == "document"}
    base = PackInputs(cfg=VISA, documents=docs, statements={"sop": "a" * 64, "cv": "b" * 64},
                      profile={"blocked_account_confirmation.amount": ProfileValue(11904.0, "document", 3)},
                      facts={}, constants={}, citations={}, ticked=set(), added=[], required_override=None)
    return replace(base, **over)


def by_key(results):
    return {r.key: r for r in results}


def test_visa_config_loads_separately():
    assert VISA.funds is not None and VISA.funds.proof_item == "blocked_account"
    packs = load_pack_configs()  # kind="pack": the visa file is not a second pack config for the route
    assert set(packs) == {"germany_master"} and packs["germany_master"].funds is None
    check_pack_config(VISA, profile_keys(TYPES), set(TYPES), BOOK, None)


def test_bad_proof_field_stops_startup(tmp_path):
    raw = yaml.safe_load((PACK_DIR / "germany_master.visa.yaml").read_text(encoding="utf-8"))
    raw["funds"]["proof_field"] = "shoe_size"
    (tmp_path / "germany_master.visa.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    cfg = load_pack_configs(tmp_path, kind="visa")["germany_master"]
    with pytest.raises(PackConfigError, match="shoe_size"):
        check_pack_config(cfg, profile_keys(TYPES), set(TYPES), BOOK, None)


def test_required_funds():
    r = required_funds(VISA.funds, fact(11904), 2000)
    assert (r.required, r.base, r.months, r.reduction) == (9904.0, 11904.0, 12, 2000.0)
    assert (r.status, r.url, r.currency_label) == ("unconfirmed", URL, VISA.funds.currency_label)


def test_full_reduction_floors_at_zero():
    """Review Focus #2: a full scholarship needs nothing more, and the proof item needs no blocked account."""
    r = required_funds(VISA.funds, fact(11904), 20000)
    assert r.required == 0.0
    item = by_key(checklist(inputs(documents={}), "p1", funds=r))["blocked_account"]
    assert item.state == "ready" and "not needed" in item.reasons[0]


def test_missing_funds_fact():
    """Review Focus #5: no funds fact is never treated as ready."""
    r = required_funds(VISA.funds, None, 0)
    assert r.required is None and r.status == "missing"
    item = by_key(checklist(inputs(), "p1", funds=r))["blocked_account"]
    assert item.state == "needs_action" and "embassy" in item.reasons[0]


def test_proof_amount_with_separators():
    """Review Focus #3: amounts read as text are compared as numbers."""
    assert as_number("11,904.00") == 11904.0 and as_number("11.904,00") == 11904.0
    assert as_number("992,50") == 992.5 and as_number("11904") == 11904.0 and as_number(11904) == 11904.0
    assert as_number("EUR 11 904") == 11904.0 and as_number("about") is None and as_number(None) is None
    r = required_funds(VISA.funds, fact(11904), 0)
    text_amount = inputs(profile={"blocked_account_confirmation.amount": ProfileValue("11,904.00", "document", 3)})
    assert by_key(checklist(text_amount, "p1", funds=r))["blocked_account"].state == "ready"


def test_proof_below_requirement_needs_action():
    r = required_funds(VISA.funds, fact(11904), 0)
    low = inputs(profile={"blocked_account_confirmation.amount": ProfileValue(10236.0, "document", 3)})
    item = by_key(checklist(low, "p1", funds=r))["blocked_account"]
    assert item.state == "needs_action" and item.reasons == [f"the amount is below what you need: 11904 {VISA.funds.currency_label}"]


def test_motivation_letter_is_the_sop():
    item = next(i for i in VISA.checklist if i.key == "motivation_letter")
    assert (item.kind, item.ref) == ("statement", "sop") and "study plan" in item.note
    assert by_key(checklist(inputs(), "p1"))["motivation_letter"].state == "ready"


def test_no_currency_in_python():
    words = re.compile(r"\beur\b|euro|€|\bpkr\b|rupee", re.IGNORECASE)
    hits = [f"{p.name}:{n}" for p in Path(PACK_DIR).glob("*.py")
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if words.search(line)]
    assert hits == []
