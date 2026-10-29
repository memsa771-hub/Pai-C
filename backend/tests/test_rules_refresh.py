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


# ---- fix round 1: the quote states the value; the rule's own domain; PDFs ------------------

@pytest.mark.asyncio
async def test_a_proposal_whose_quote_lacks_the_new_value_is_dropped(tmp_path):
    values = {RULE_URL: [{"path": "admission_rules.json:rules/0/min_percent", "value": 70,
                          "quote": "Candidates need at least 65% marks in HSSC.", "confidence": "official"}],
              EVENT_URL: [{"path": "academic_calendar.json:events/0/months", "value": [6],
                           "quote": "The annual examination will be held in May 2027.", "confidence": "official"}]}
    proposal, *_ = await refresh(tmp_path, values=values)
    assert proposal["diffs"] == []


@pytest.mark.asyncio
async def test_a_short_quote_is_dropped(tmp_path):
    page = {RULE_URL: "65%", EVENT_URL: PAGE[EVENT_URL]}
    read = AsyncMock(side_effect=lambda url, chars: {"url": url, "text": page[url]})
    values = {RULE_URL: [{"path": "admission_rules.json:rules/0/min_percent", "value": 65, "quote": "65%",
                          "confidence": "official"}]}
    with patch.object(rules_refresh, "read_page", read), patch.object(rules_refresh, "complete", model_for(values)):
        target = await run_refresh(max_calls=60, out_dir=tmp_path, today=TODAY, files=FILES)
    assert json.loads(target.read_text())["diffs"] == []


@pytest.mark.asyncio
async def test_refresh_reads_only_the_rule_s_own_domain(tmp_path):
    moved = AsyncMock(side_effect=lambda url, chars: {"url": "https://elsewhere.example.com/page", "text": PAGE[url]})
    with patch.object(rules_refresh, "read_page", moved), patch.object(rules_refresh, "complete", AsyncMock()) as model:
        target = await run_refresh(max_calls=60, out_dir=tmp_path, today=TODAY, files=FILES)
    proposal = json.loads(target.read_text())
    assert sorted(proposal["unread_sources"]) == sorted([RULE_URL, EVENT_URL]) and proposal["diffs"] == []
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_job_is_gated_on_the_role_it_calls():
    with patch.object(usage, "role_allowed", lambda role: role != "researcher"), \
            patch.object(rules_refresh, "run_refresh", AsyncMock()) as run:
        assert (await rules_refresh_job(SimpleNamespace(payload={}), Mock()))["status"] == "cap_paused"
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_second_run_on_the_same_day_keeps_the_first_file(tmp_path):
    _, first, *_ = await refresh(tmp_path)
    _, second, *_ = await refresh(tmp_path)
    assert first != second and first.exists() and second.exists()


def text_pdf(text: str) -> bytes:
    """A one-page PDF with one line of text, built by hand."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
               b"/Resources << /Font << /F1 5 0 R >> >> >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("truncated", [False, True])
async def test_read_page_reads_a_pdf_source(truncated):
    from app.plugins._shared import sources
    from app.security.network import SafeFetchResult
    sentence = "Candidates need at least 60 percent marks in HSSC Pre-Engineering."
    url = "https://www.pec.org.pk/wp-content/uploads/REGULATIONS.pdf"
    fetched = SafeFetchResult(text_pdf(sentence), 200, {"content-type": "application/pdf"}, url, truncated)
    with patch("app.security.network.safe_fetch", AsyncMock(return_value=fetched)):
        page = await sources.read_page(url, 5000)
    if truncated:
        assert page is None  # a cut PDF cannot be parsed
    else:
        assert page == {"url": url, "text": sentence}


@pytest.mark.asyncio
async def test_read_page_still_reads_html():
    from app.plugins._shared import sources
    from app.security.network import SafeFetchResult
    url = "https://www.hec.gov.pk/page"
    html = b"<html><body><p>The degree lasts four years for every student.</p></body></html>"
    fetched = SafeFetchResult(html, 200, {"content-type": "text/html; charset=utf-8"}, url, False)
    with patch("app.security.network.safe_fetch", AsyncMock(return_value=fetched)):
        page = await sources.read_page(url, 5000)
    assert page["text"] == "The degree lasts four years for every student."


def test_apply_reverts_when_validation_raises_and_marks_the_proposal(tmp_path):
    folder, proposal = policy_copy(tmp_path), real_proposal(tmp_path)
    original = (folder / "admission_rules.json").read_bytes()

    def boom():
        raise RuntimeError("pytest could not start")
    with pytest.raises(RuntimeError):
        apply_refresh.apply_proposal(proposal, policy_dir=folder, validate=boom)
    assert (folder / "admission_rules.json").read_bytes() == original
    apply_refresh.apply_proposal(proposal, policy_dir=folder, validate=lambda: True)
    marked = json.loads(proposal.read_text(encoding="utf-8"))
    assert marked["applied"] == ["admission_rules.json:rules/0/min_percent", "academic_calendar.json:events/0/months"]


# ---- fix round 2: months beside a date, percents beside a percent sign; PDF off the loop -------

@pytest.mark.parametrize("field,value,quote,stated", [
    ("apply_months", [5], "Candidates may apply online through the portal after the results are announced this year.", False),
    ("months", [5], "The annual examination will be held in May 2027 across the province.", True),
    ("months", [3], "Papers begin on 27 March and continue for three weeks across the province.", True),
    ("min_percent", 60, "Registration remains open for 60 days and the minimum marks required are 65 percent overall.", False),
    ("min_percent", 65, "Registration remains open for 60 days and the minimum marks required are 65 percent overall.", True),
    ("min_percent", 65, "Candidates need at least 65% marks in HSSC Pre-Engineering to apply.", True),
    ("years", 4, "The degree lasts 4 years of full-time study at an accredited university.", True),
])
def test_the_quote_states_the_value_in_its_own_context(field, value, quote, stated):
    page = {"text": quote}
    assert rules_refresh._verified({"quote": quote, "value": value}, {"field": field}, page,
                                   rules_refresh.policy()) is stated


@pytest.mark.asyncio
async def test_pdf_text_is_extracted_off_the_event_loop():
    from app.plugins._shared import sources
    from app.security.network import SafeFetchResult
    url = "https://www.pec.org.pk/rules.pdf"
    fetched = SafeFetchResult(text_pdf("Candidates need at least 60 percent marks in HSSC."), 200,
                              {"content-type": "application/pdf"}, url, False)
    calls = []

    async def to_thread(function, *args):
        calls.append(function.__name__)
        return function(*args)
    with patch("app.security.network.safe_fetch", AsyncMock(return_value=fetched)), \
            patch.object(sources.asyncio, "to_thread", to_thread):
        page = await sources.read_page(url, 5000)
    assert calls == ["parse_pdf"] and page["text"].startswith("Candidates need")


@pytest.mark.asyncio
async def test_job_writes_to_the_configured_proposals_dir(tmp_path):
    """PAI_PROPOSALS_DIR (mounted from the host in docker-compose) holds the
    proposal; apply_refresh finds the newest one there by itself."""
    from app.config import config
    folder = tmp_path / "proposals"
    read = AsyncMock(side_effect=lambda url, chars: {"url": url, "text": PAGE[url]})
    with patch.object(config, "PAI_PROPOSALS_DIR", str(folder)), \
            patch.object(rules_refresh, "read_page", read), \
            patch.object(rules_refresh, "complete", model_for(VALUES)), \
            patch.object(rules_refresh, "refresh_items", lambda files=None: refresh_items(FILES)):
        assert rules_refresh.proposals_dir() == folder
        result = await rules_refresh_job(SimpleNamespace(payload={}), Mock())
        assert result["status"] == "proposed" and (folder / result["file"]).exists()
        assert apply_refresh.resolve_proposal(None) == folder / result["file"]
        assert apply_refresh.resolve_proposal(Path(result["file"])) == folder / result["file"]
    with patch.object(config, "PAI_PROPOSALS_DIR", ""):
        assert rules_refresh.proposals_dir() == POLICY_DIR / rules_refresh.policy()["proposals_dir"]
