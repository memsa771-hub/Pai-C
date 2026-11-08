"""P2-T8 review fixes (R-61, R-63, R-65, R-26): the backfill leaves a revision, every entry path honours R-63, an
upgrade to a version must cover the plan's intake, and the fallback reads one defined earlier year. Fictional data."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import insert

from app.os import models
from app.os.intakes import IntakeError, IntakeStore
from app.os.intakes.rollover import backfill_intake_terms, rollover
from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge
from app.os.playbooks import Playbook, load_playbook
from tests.os.test_compiler import FAKE, IE
from tests.os.test_p2_intakes_proof import contract, world  # noqa: F401  (fixture)

pytestmark = pytest.mark.req("R-61")
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)


def test_backfill_records_a_revision_for_each_updated_fact(engine, clean):
    one = load_playbook(FAKE / "ireland_master.v1.yaml")
    term = one.intake_terms[0]
    with engine.begin() as conn:
        conn.execute(insert(models.programmes).values(tenant_id="pai", ref="pa", route_key=one.key, university="u",
                                                      name="n"))
    k = SqlKnowledge(engine, "pai")
    fid = k.upsert("programme", "pa", "fee", Fact(value=1, quote="q", url="https://a.test/x", checked_at=AT,
                                                  status="confirmed", intake_year=2027))
    assert backfill_intake_terms(engine, "pai", {(one.key, 1): one}).updated == 1
    last = k.revisions(fid)[-1]
    assert (last.cause, last.cause_ref, last.actor) == ("backfill", "D-t1-1", "os.rollover")
    assert last.before["intake_term"] == "" and last.after["intake_term"] == term
    assert backfill_intake_terms(engine, "pai", {(one.key, 1): one}).updated == 0
    assert len(k.revisions(fid)) == 2  # the second run wrote nothing


def test_backfill_takes_the_union_of_terms_across_versions(engine, clean):
    one = load_playbook(FAKE / "ireland_master.v1.yaml")
    v2 = one.model_copy(update={"version": 2, "intake_terms": ["spring"]})
    assert one.intake_terms != v2.intake_terms
    with engine.begin() as conn:
        conn.execute(insert(models.programmes).values(tenant_id="pai", ref="pa", route_key=one.key, university="u",
                                                      name="n"))
    SqlKnowledge(engine, "pai").upsert("programme", "pa", "fee", Fact(
        value=1, quote="q", url="https://a.test/x", checked_at=AT, status="confirmed", intake_year=2027))
    res = backfill_intake_terms(engine, "pai", {(one.key, 1): one, (one.key, 2): v2})
    assert res.updated == 0 and [s.reason for s in res.skipped] == ["several_terms"]  # no guess between versions


def test_start_plan_refuses_a_registered_intake_that_is_not_open(world, engine):  # noqa: F811
    svc, _kb, _kernel, s = world
    s.create("r_one", "masters", "winter", 2028)  # registered, planned
    with pytest.raises(IntakeError, match="not open"):
        svc.start_plan(contract(2028, "late"))
    rollover(engine, "pai", region="r_one", family="masters", term="winter", year=2028)  # now open
    assert svc.start_plan(contract(2028, "late")).created
    s.set_state(s.get("r_one", "masters", "winter", 2028).id, "closed")
    with pytest.raises(IntakeError, match="not open"):
        svc.start_plan(contract(2028, "other"))
    assert svc.start_plan(contract(2028, "late")).created is False  # a plan that exists is still returned


@pytest.mark.req("R-65")
def test_upgrade_to_a_version_that_does_not_cover_the_intake_is_refused(world, engine):  # noqa: F811
    svc, *_ = world
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    v2 = Playbook.model_validate({**data, "version": IE.version + 1,
                                  "applies_to": {"term": "winter", "from_year": 2030}})
    svc.playbooks[(v2.key, v2.version)] = v2
    plan_id = svc.start_plan(contract(2027, "up")).plan_id
    with pytest.raises(ValueError, match="does not cover"):
        svc.upgrade(plan_id, version=v2.version)


@pytest.mark.req("R-26")
def test_fallback_reads_only_the_opened_from_year_else_the_year_before(engine, clean):
    s = IntakeStore(engine, "pai")
    assert s.fallback_year("fall", 2028) is None  # no intake registered: no fallback
    i26 = s.create("r_one", "ug", "fall", 2026, state="open")
    s.set_state(i26.id, "current", gate_passed_at=AT)
    s.create("r_one", "ug", "fall", 2028, state="open", opened_from_id=i26.id)  # 2027 was skipped
    assert s.fallback_year("fall", 2028) == 2026
    s.create("r_two", "ug", "fall", 2029, state="open")  # opened from nothing: the year before
    assert s.fallback_year("fall", 2029) == 2028

    k = SqlKnowledge(engine, "pai")

    def put(year, value):
        k.upsert("programme", "p", "deadline", Fact(value=value, quote="q", url="https://a.test/x", checked_at=AT,
                                                    status="confirmed", intake_year=year, intake_term="fall"))

    put(2025, "y25")
    put(2026, "y26")
    got = k.programme_facts(["p"], ["deadline"], 2028, intake_term="fall", fallback_previous=True, fallback_year=2026)
    assert got[("p", "deadline")].value == "y26"
    got = k.programme_facts(["p"], ["deadline"], 2028, intake_term="fall", fallback_previous=True, fallback_year=2027)
    assert got == {}  # 2025 and 2026 are not 2027: never a year the intake was not opened from
    # without a year the newest earlier one is read, as T1 defined it
    assert k.programme_facts(["p"], ["deadline"], 2028, intake_term="fall",
                             fallback_previous=True)[("p", "deadline")].value == "y26"
