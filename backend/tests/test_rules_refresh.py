"""Monthly rules and calendar refresh (BETA_CONVERSATION_SPEC 3.3): a proposal
file of verified diffs from mocked pages and model; the policy files are never
edited by the refresh; scripts/apply_refresh applies a reviewed proposal and
keeps it only when validation passes."""

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from sqlalchemy import select

from app.inference import usage
from app.models import BackgroundJob
from app.pai_c.policy.controller import POLICY_DIR
from app.research import rules_refresh
from app.research.rules_refresh import JOB_RULES_REFRESH, refresh_items, rules_refresh_job, run_refresh
from app.research.scheduler import enqueue_monthly_rules_refresh
from scripts import apply_refresh
from scripts.counselor_eval_support import StudentSession

RULE_URL = "https://rules.example.org/engineering"
EVENT_URL = "https://board.example.org/datesheet"
PAGE = {RULE_URL: "Candidates need at least 65% marks in HSSC. The degree lasts four years.",
        EVENT_URL: "The annual examination will be held in May 2027."}
FILES = {
    "admission_rules.json": {"rules": [
        {"applies_to": {"fields": ["x"]}, "min_percent": 60, "years": 4, "sources": [RULE_URL],
         "entry_tests": [{"name": "Test", "pass_percent": 33, "source": "http://insecure.example.org"}]}]},
    "academic_calendar.json": {"_note": "n", "events": [
        {"key": "exam", "label": "Annual exam", "months": [3, 4], "sources": [EVENT_URL]},
        {"key": "no_source", "label": "No source", "months": [1], "sources": []}],
        "tests": [], "intakes": [], "regions": {"punjab": {"boards": ["A"], "exam": {
            "months": [3], "sources": [EVENT_URL], "month_note": "Punjab exam"}}}},
}
TODAY = datetime(2026, 11, 1, tzinfo=timezone.utc)


def model_for(values_by_url):
    async def model(**kwargs):
        sent = json.loads(kwargs["messages"][0]["content"])
        return json.dumps({"values": values_by_url.get(sent["source_url"], [])})
    return AsyncMock(side_effect=model)


VALUES = {
    RULE_URL: [
        {"path": "admission_rules.json:rules/0/min_percent", "value": 65,
         "quote": "Candidates need at least 65% marks in HSSC.", "confidence": "official"},
        {"path": "admission_rules.json:rules/0/years", "value": 4,
         "quote": "The degree lasts four years.", "confidence": "official"},  # unchanged: no diff
    ],
    EVENT_URL: [
        {"path": "academic_calendar.json:events/0/months", "value": [5],
         "quote": "The annual examination will be held in May 2027.", "confidence": "bogus"},
        {"path": "academic_calendar.json:regions/punjab/exam/months", "value": [6],
         "quote": "held in June", "confidence": "official"},  # quote not on the page: dropped
        {"path": "academic_calendar.json:events/1/months", "value": [2],
         "quote": "The annual examination", "confidence": "official"},  # not asked for this URL
    ],
}


async def refresh(tmp_path, *, values=VALUES, max_calls=60):
    read = AsyncMock(side_effect=lambda url, chars: {"url": url, "text": PAGE[url]})
    model = model_for(values)
    with patch.object(rules_refresh, "read_page", read), patch.object(rules_refresh, "complete", model):
        target = await run_refresh(max_calls=max_calls, out_dir=tmp_path, today=TODAY, files=FILES)
    return json.loads(target.read_text(encoding="utf-8")), target, read, model


def test_items_come_from_the_policy_targets():
    items = refresh_items(FILES)
    assert [item["path"] for item in items] == [
        "admission_rules.json:rules/0/min_percent", "admission_rules.json:rules/0/years",
        "academic_calendar.json:events/0/months", "academic_calendar.json:regions/punjab/exam/months"]
    # The real policy files have checkable rows with https sources.
    real = refresh_items()
    assert {item["file"] for item in real} == {"admission_rules.json", "academic_calendar.json"}
    assert all(item["source_url"].startswith("https://") for item in real)


@pytest.mark.asyncio
async def test_refresh_writes_a_proposal_and_never_edits_policy(tmp_path):
    before = {name: (POLICY_DIR / name).read_bytes() for name in ("admission_rules.json", "academic_calendar.json")}
    proposal, target, read, model = await refresh(tmp_path)
    assert target == tmp_path / "2026-11-01.json"
    assert proposal["diffs"] == [
        {"path": "admission_rules.json:rules/0/min_percent", "old": 60, "new": 65,
         "quote": "Candidates need at least 65% marks in HSSC.", "source_url": RULE_URL, "confidence": "official"},
        {"path": "academic_calendar.json:events/0/months", "old": [3, 4], "new": [5],
         "quote": "The annual examination will be held in May 2027.", "source_url": EVENT_URL,
         "confidence": "secondary"},
    ]
    assert proposal["applied"] is False and proposal["checked_items"] == 4
    # One page read and one `researcher` call per source URL.
    assert read.await_count == 2 and model.await_count == 2
    assert all(call.kwargs["role"] == "researcher" for call in model.await_args_list)
    assert {name: (POLICY_DIR / name).read_bytes() for name in before} == before


@pytest.mark.asyncio
async def test_budget_and_unreadable_sources(tmp_path):
    proposal, _, read, model = await refresh(tmp_path, max_calls=2)
    assert read.await_count == 1 and model.await_count == 1
    assert proposal["skipped_for_budget"] == 2 and proposal["checked_items"] == 2
    with patch.object(rules_refresh, "read_page", AsyncMock(return_value=None)), \
            patch.object(rules_refresh, "complete", AsyncMock()) as never:
        target = await run_refresh(max_calls=60, out_dir=tmp_path, today=TODAY, files=FILES)
    assert sorted(json.loads(target.read_text())["unread_sources"]) == sorted([RULE_URL, EVENT_URL])
    never.assert_not_awaited()


@pytest.mark.asyncio
async def test_research_paused_skips_the_job():
    paused = {"month": "", "spent": 85.0, "cap": 100.0, "stage": "research_paused"}
    with patch.object(usage, "cap_state", lambda: paused), patch.object(usage, "_gate_logged", {}), \
            patch.object(rules_refresh, "run_refresh", AsyncMock()) as run:
        assert await rules_refresh_job(SimpleNamespace(payload={}), Mock()) == {"status": "cap_paused"}
    run.assert_not_awaited()


def test_scheduled_once_a_month():
    with StudentSession() as student, student.factory() as db:
        first = enqueue_monthly_rules_refresh(db, now=TODAY)
        again = enqueue_monthly_rules_refresh(db, now=TODAY.replace(day=20))
        later = enqueue_monthly_rules_refresh(db, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
        db.commit()
        jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_RULES_REFRESH)).all()
    assert first.id == again.id != later.id and len(jobs) == 2


# ---- scripts/apply_refresh -----------------------------------------------------------------

def policy_copy(tmp_path) -> Path:
    folder = tmp_path / "policy"
    folder.mkdir(parents=True)
    for name in ("admission_rules.json", "academic_calendar.json", "rules_refresh.json"):
        shutil.copy(POLICY_DIR / name, folder / name)
    return folder


def real_proposal(tmp_path) -> Path:
    rules = json.loads((POLICY_DIR / "admission_rules.json").read_text(encoding="utf-8"))
    calendar = json.loads((POLICY_DIR / "academic_calendar.json").read_text(encoding="utf-8"))
    diffs = [
        {"path": "admission_rules.json:rules/0/min_percent", "old": rules["rules"][0]["min_percent"], "new": 65,
         "quote": "q", "source_url": RULE_URL, "confidence": "official"},
        {"path": "academic_calendar.json:events/0/months", "old": calendar["events"][0]["months"], "new": [5],
         "quote": "q", "source_url": EVENT_URL, "confidence": "official"},
        {"path": "admission_rules.json:rules/1/years", "old": -1, "new": 9,
         "quote": "q", "source_url": RULE_URL, "confidence": "official"},  # changed since: stale
    ]
    target = tmp_path / "proposal.json"
    target.write_text(json.dumps({"diffs": diffs}), encoding="utf-8")
    return target


def test_apply_applies_a_proposal_after_validation(tmp_path):
    folder, proposal = policy_copy(tmp_path), real_proposal(tmp_path)
    original = (folder / "admission_rules.json").read_bytes()
    validate = Mock(return_value=True)
    result = apply_refresh.apply_proposal(proposal, policy_dir=folder, validate=validate)
    assert result["applied"] == ["admission_rules.json:rules/0/min_percent", "academic_calendar.json:events/0/months"]
    assert result["stale"] == ["admission_rules.json:rules/1/years"] and result["valid"]
    validate.assert_called_once()
    rules = json.loads((folder / "admission_rules.json").read_text(encoding="utf-8"))
    calendar = json.loads((folder / "academic_calendar.json").read_text(encoding="utf-8"))
    assert rules["rules"][0]["min_percent"] == 65 and calendar["events"][0]["months"] == [5]
    # Everything else is unchanged, and the file keeps its line endings.
    before = json.loads(original.decode("utf-8"))
    before["rules"][0]["min_percent"] = 65
    assert rules == before
    assert (b"\r\n" in original) == (b"\r\n" in (folder / "admission_rules.json").read_bytes())


def test_apply_only_and_revert_on_failed_validation(tmp_path):
    folder, proposal = policy_copy(tmp_path), real_proposal(tmp_path)
    original = {name: (folder / name).read_bytes() for name in ("admission_rules.json", "academic_calendar.json")}
    only = apply_refresh.apply_proposal(proposal, ["academic_calendar.json:events/0/months"],
                                        policy_dir=folder, validate=lambda: True)
    assert only["applied"] == ["academic_calendar.json:events/0/months"]
    assert (folder / "admission_rules.json").read_bytes() == original["admission_rules.json"]
    folder2 = policy_copy(tmp_path / "second")
    failed = apply_refresh.apply_proposal(proposal, policy_dir=folder2, validate=lambda: False)
    assert failed["valid"] is False and failed["applied"] == []
    assert {name: (folder2 / name).read_bytes() for name in original} == original


def test_apply_validates_with_the_admission_rules_and_calendar_tests(tmp_path):
    folder, proposal = policy_copy(tmp_path), real_proposal(tmp_path)
    with patch.object(apply_refresh, "run_validation", return_value=True) as run:
        assert apply_refresh.apply_proposal(proposal, policy_dir=folder)["valid"]
    tests = run.call_args.args[0]
    assert tests == ["tests/test_admission_rules.py", "tests/test_academic_calendar.py"]
    assert all((Path(apply_refresh.BACKEND) / test).exists() for test in tests)
