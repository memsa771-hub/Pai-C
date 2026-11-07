"""P2-T4: not_readable marking, the OCR status ceiling, read_method and language on researched facts (R-72, R-29)."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import insert

from app.os import models
from app.os.knowledge.profile import PROFILE_DIR, load_profile_dir
from app.os.knowledge.research.readability import (
    NotReadableStore,
    is_not_readable,
    machine_status_ceiling,
)
from app.os.knowledge.research.run import store_research
from app.os.knowledge.store import SqlKnowledge

pytestmark = pytest.mark.req("R-72", "R-29")
NOW = datetime(2027, 5, 2, 10, tzinfo=UTC)
PROFILE = load_profile_dir(PROFILE_DIR)["germany_master"]
URL = "https://www.alpha-university.test/notice.png"


def test_which_refusals_need_a_person():
    for blocked in ("not_readable:render", "not_readable:ocr", "http_401", "http_403", "unreadable_pdf",
                    "unsupported:image/png"):
        assert is_not_readable(blocked)
    for blocked in (None, "", "robots", "not_official", "http_404", "too_big", "integrity:spam", "unsupported:text/csv",
                    "suspect_domain"):
        assert not is_not_readable(blocked)


def test_machine_ceiling_by_read_method():
    assert [machine_status_ceiling(m) for m in (None, "fetch", "render", "model", "ocr", "human")] == [
        "confirmed", "confirmed", "confirmed", "confirmed", "unconfirmed", "unconfirmed"]


def test_store_marks_source_and_fields_and_reopens(engine, clean):
    s = NotReadableStore(engine, "pai", clock=lambda: NOW)
    assert s.mark(URL, "not_readable:ocr", programme_ref="p1", fields=["deadline_close", "fee"], intake_year=2027) == 3
    assert {r.field for r in s.open_rows(programme_ref="p1")} == {"", "deadline_close", "fee"}
    assert s.mark(URL, "http_403", programme_ref="p1", fields=["fee"], intake_year=2027) == 2  # same rows, new reason
    assert len(s.open_rows()) == 3 and {r.reason for r in s.open_rows() if r.field == "fee"} == {"http_403"}
    assert s.set_state(URL, "collected", programme_ref="p1", field="fee") == 1
    assert s.set_state(URL, "readable", programme_ref="p1") == 2  # the others: a collected row is left alone
    assert s.open_rows() == []
    s.mark(URL, "not_readable:ocr", programme_ref="p1", fields=["fee"], intake_year=2027)
    assert {r.field for r in s.open_rows()} == {""}  # a failed read reopens readable rows; collected stays collected


def _verdict(url, status="confirmed"):
    return {"deadline_close": {"status": status, "value": "07-01", "quote": "Closes 1 July.", "url": url,
                               "conflict_note": None, "evidence": []}}


def _store(engine, verdicts, read_info=None, unreadable=(), nr=None, ref="p1"):
    service = SimpleNamespace(engine=engine, check_fact_value=lambda f, v: None, recompile=lambda pid, why: None)
    kernel = SimpleNamespace(tenant_id="pai")
    with engine.begin() as conn:
        run_id = conn.execute(insert(models.research_runs).values(
            tenant_id="pai", programme_ref=ref, intake_year=2027, workflow_id=f"w-{ref}-{read_info}").returning(
            models.research_runs.c.id)).scalar_one()
    counts = store_research(engine, service, kernel, run_id, ref, 2027, PROFILE, verdicts, NOW, read_info, unreadable, nr)
    return counts, SqlKnowledge(engine, "pai").programme_facts([ref], ["deadline_close"], 2027)[(ref, "deadline_close")]


def test_a_fact_read_by_ocr_stays_unconfirmed_with_its_read_method(engine, clean):
    counts, fact = _store(engine, _verdict(URL), {URL: {"read_method": "ocr", "language": "ur"}})
    assert (counts["confirmed"], counts["unconfirmed"]) == (0, 1)
    assert (fact.status, fact.read_method, fact.language) == ("unconfirmed", "ocr", "ur")


def test_a_fact_read_after_rendering_can_be_confirmed(engine, clean):
    counts, fact = _store(engine, _verdict(URL), {URL: {"read_method": "render", "language": None}})
    assert counts["confirmed"] == 1 and (fact.status, fact.read_method, fact.language) == ("confirmed", "render", None)


def test_plain_fetch_facts_are_stored_as_before(engine, clean):
    _, fact = _store(engine, _verdict(URL), {URL: {"read_method": "fetch", "language": None}})
    assert (fact.status, fact.read_method, fact.language) == ("confirmed", None, None)
    _, fact2 = _store(engine, _verdict(URL), None, ref="p2")
    assert (fact2.status, fact2.read_method) == ("confirmed", None)


def test_unreadable_pages_mark_only_fields_without_a_confirmed_fact(engine, clean):
    nr = NotReadableStore(engine, "pai", clock=lambda: NOW)
    bad = [{"url": "https://www.alpha-university.test/scan.pdf", "reason": "not_readable:ocr"}]
    _store(engine, _verdict(URL), None, bad, nr)
    fields = {r.field for r in nr.open_rows(programme_ref="p1")}
    assert "" in fields and "deadline_close" not in fields  # the confirmed field is not asked of a person
    assert "tuition_fee_non_eu_eur" in fields
    _store(engine, _verdict(URL), None, bad, None, ref="p3")  # no store given: nothing written (flags off)
    assert nr.open_rows(programme_ref="p3") == []
