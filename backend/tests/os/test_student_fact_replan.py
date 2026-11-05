"""P1-T4 Task 6: a Vault fact change replans (R-15, R-16, R-13). The fake Pakistan bachelor route; invented marks
and a fake merit threshold. Postgres. The rule is pure; the events and the proposal go through the real services."""

import types as pytypes
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.os.api import make_services
from app.os.contracts.route_contract import RouteContract
from app.os.contracts.student_facts import StudentFactsV1
from app.os.documents.types import DocumentType, FieldSpec
from app.os.eligibility import facts as eligibility_facts
from app.os.eligibility.facts import current_types
from app.os.kernel import Kernel
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.ports import student_facts
from app.os.replan.apply import ProposalStale, Replanner
from app.os.replan.checks import task_rows
from app.os.replan.config import ReplanConfig, load_replan_configs
from app.os.replan.events import Event, pending
from app.os.replan.ops import CancelProgramme, Escalate
from app.os.replan.rules import REASONS, PlanState, rules_for
from app.os.settings import load_settings

pytestmark = [pytest.mark.req("R-15"), pytest.mark.req("R-16"), pytest.mark.req("R-13")]

FAKE = Path(__file__).parent / "playbooks"
TENANT, NOW = "pai", datetime(2026, 11, 5, tzinfo=timezone.utc)
URL = "https://uni.example/x"
MARKS = "education.intermediate.marks_obtained"
TOTAL = "education.intermediate.marks_total"
ENTRY = "test.entry_test.score"
EV = models.events
# the fake local entry test is not a shipped document type: this test adds one so the mapping covers it
ENTRY_TYPE = DocumentType(key="entry_test", version=1, label="Entry test",
                          fields=[FieldSpec(name="score", type="number", hint="Score", fact=ENTRY)])


def vault_event(version, keys, student="stu-1") -> dict:
    return {"schema": "pai.vault_event.v1", "key": f"vault_event:{student}:{version}", "student_ref": student,
            "vault_version": version, "kind": "student_fact_changed", "keys": list(keys), "at": NOW.isoformat()}


def facts_for(student, version, obtained) -> dict:
    items = [{"key": MARKS, "value": obtained, "evidence": "stated", "vault_version": version},
             {"key": TOTAL, "value": 1100, "evidence": "stated", "vault_version": version},
             {"key": ENTRY, "value": 80, "evidence": "stated", "vault_version": version}]
    return StudentFactsV1.model_validate({"schema": "pai.student_facts.v1", "student_ref": student,
                                          "vault_version": version, "built_at": NOW, "eligible_levels": None,
                                          "facts": items}).model_dump(by_alias=True)


def contract(student, refs=("p-easy", "p-hard")) -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"self:{student}:{len(refs)}", "student_ref": student,
        "origin_country": "PK", "destination_country": "PK", "level": "bachelor",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


@pytest.fixture
def world(engine, clean, os_db):
    """Two programmes with fake merit closings (50 and 80) on the fake route; the Vault answers from a dict."""
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true"})
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2026, 11, 5))
    store, kb = ProgrammeStore(engine, TENANT), SqlKnowledge(engine, TENANT)
    for ref, closing in (("p-easy", 50), ("p-hard", 80)):
        store.upsert(Programme(ref=ref, route_key="pakistan_bs", university="Uni X", name=ref, aliases=(),
                               start_urls=("https://uni.example/x",), official_domains=("uni.example",)))
        for field, value in (("merit_closing", {"aggregate": closing}), ("entry_test_required", {"any_of": []})):
            kb.upsert("programme", ref, field, Fact(value, "q", "https://uni.example/x", NOW, 2027, "confirmed"),
                      "manual")
    vault: dict[str, dict] = {}
    ports.configure(svc, student_facts=lambda ref: vault.get(ref))
    eligibility_facts.configure_types(current_types() | {"entry_test": ENTRY_TYPE})
    manifest.set_enabled(engine, TENANT, True)
    replanner = Replanner(engine, svc.plans, load_replan_configs(), Outbox(engine, TENANT), clock=lambda: NOW)
    try:
        yield pytypes.SimpleNamespace(svc=svc, engine=engine, vault=vault, replanner=replanner)
    finally:
        ports.configure(None)


def start(world, student="stu-1", refs=("p-easy", "p-hard")) -> int:
    return world.svc.plans.start_plan(contract(student, refs)).plan_id


def fact_events(engine, plan_id=None) -> list:
    q = select(EV.c.plan_id, EV.c.payload).where(EV.c.type == "student_fact_changed").order_by(EV.c.id)
    if plan_id is not None:
        q = q.where(EV.c.plan_id == plan_id)
    with engine.connect() as conn:
        return [(r.plan_id, r.payload) for r in conn.execute(q)]


# --- the port records a replan event --------------------------------------------------------------------------

def test_a_used_key_records_one_event_on_each_open_plan_deduped_by_version(world):
    first, second = start(world), start(world, refs=("p-hard",))
    other = start(world, "stu-2")
    assert student_facts.record_event(vault_event(3, [MARKS, "test.ielts.score"])) == "stored"
    assert fact_events(world.engine) == [(first, {"keys": [MARKS], "vault_version": 3, "dedupe": "3"}),
                                         (second, {"keys": [MARKS], "vault_version": 3, "dedupe": "3"})]
    assert student_facts.record_event(vault_event(3, [MARKS])) == "duplicate"  # delivered again: nothing more
    assert len(fact_events(world.engine)) == 2
    assert student_facts.record_event(vault_event(4, [MARKS])) == "stored"  # a new version is a new event
    assert len(fact_events(world.engine, first)) == 2 and fact_events(world.engine, other) == []


def test_an_unused_key_records_nothing(world):
    start(world)
    assert student_facts.record_event(vault_event(2, ["test.ielts.score", "education.master.gpa"])) == "stored"
    assert fact_events(world.engine) == []


def test_a_constraint_key_records_an_event_and_a_closed_plan_none(world):
    plan_id = start(world)
    done = start(world, "stu-3")
    with world.engine.begin() as conn:
        conn.execute(models.plans.update().where(models.plans.c.id == done).values(status="closed"))
    for ref in ("stu-1", "stu-3"):
        student_facts.record_event(vault_event(2, ["constraint.excluded_fields"], ref))
    assert [p for p, _ in fact_events(world.engine)] == [plan_id]


def test_with_the_module_off_the_event_is_stored_but_no_replan_event_is_recorded(world):
    start(world)
    manifest.set_enabled(world.engine, TENANT, False)
    assert student_facts.record_event(vault_event(2, [MARKS])) == "module_off"
    assert fact_events(world.engine) == []


# --- the rule ---------------------------------------------------------------------------------------------------

def state(below=()) -> PlanState:
    return PlanState(1, "r", ["a", "b"], {}, below=tuple(below))


def test_rule_proposes_cancelling_only_programmes_that_read_below():
    event = Event(1, 1, None, "student_fact_changed", {"keys": [MARKS], "vault_version": 2})
    assert rules_for(event, state(["b"]), ReplanConfig()) == [
        CancelProgramme(programme_ref="b", reason=REASONS["fact_below"])]
    assert rules_for(event, state(), ReplanConfig()) == []
    assert rules_for(event, state(["gone"]), ReplanConfig()) == []


# --- the replan decision ---------------------------------------------------------------------------------------

def run_rule(world, plan_id, event_id):
    """What the os.replan workflow's rules and decide steps do, called directly."""
    e = next(x for x in pending(world.engine, TENANT, plan_id) if x.id == event_id)
    got = rules_for(e, world.replanner.state(plan_id, with_below=True), world.replanner.config(plan_id))
    return world.replanner.decide(plan_id, [event_id], "rules", got)


def event_id(engine, plan_id) -> int:
    with engine.connect() as conn:
        return conn.execute(select(EV.c.id).where(EV.c.plan_id == plan_id, EV.c.type == "student_fact_changed")
                            .order_by(EV.c.id.desc())).scalars().first()


def test_marks_dropping_below_a_threshold_gives_a_pending_big_proposal_never_an_applied_cancel(world):
    plan_id = start(world)
    world.vault["stu-1"] = facts_for("stu-1", 1, 1000)  # about 91 percent: both programmes fit
    student_facts.record_event(vault_event(1, [MARKS]))
    assert run_rule(world, plan_id, event_id(world.engine, plan_id)).status == "applied"  # nothing to change
    world.vault["stu-1"] = facts_for("stu-1", 2, 800)  # about 73 percent: the 80 closing no longer fits
    student_facts.record_event(vault_event(2, [MARKS]))
    decision = run_rule(world, plan_id, event_id(world.engine, plan_id))
    assert decision.status == "pending"
    proposal = world.replanner.proposals.get(decision.proposal_id)
    assert proposal.big and proposal.status == "pending"
    assert [(o["op"], o["programme_ref"]) for o in proposal.ops] == [("cancel_programme", "p-hard")]
    live = [p.programme_ref for p in world.svc.plans._contract(plan_id)[0].programmes]
    assert live == ["p-easy", "p-hard"]  # nothing was removed by itself
    N = models.eligibility_notes  # the eligibility note was refreshed for the student
    with world.engine.connect() as conn:
        assert [(n.programme_ref, n.verdict) for n in conn.execute(select(N))] == [("p-hard", "likely_below")]


def test_a_second_change_does_not_propose_the_same_removal_again(world):
    plan_id = start(world)
    world.vault["stu-1"] = facts_for("stu-1", 1, 1000)
    student_facts.record_event(vault_event(1, [MARKS]))
    run_rule(world, plan_id, event_id(world.engine, plan_id))
    world.vault["stu-1"] = facts_for("stu-1", 2, 800)
    student_facts.record_event(vault_event(2, [MARKS]))
    assert run_rule(world, plan_id, event_id(world.engine, plan_id)).status == "pending"
    world.vault["stu-1"] = facts_for("stu-1", 3, 700)
    student_facts.record_event(vault_event(3, [MARKS]))
    assert run_rule(world, plan_id, event_id(world.engine, plan_id)).status == "applied"
    assert len(world.replanner.proposals.pending_for("stu-1")) == 1


def test_the_student_accepting_the_proposal_removes_the_programme(world):
    plan_id = start(world)
    world.vault["stu-1"] = facts_for("stu-1", 1, 1000)
    student_facts.record_event(vault_event(1, [MARKS]))
    run_rule(world, plan_id, event_id(world.engine, plan_id))
    world.vault["stu-1"] = facts_for("stu-1", 2, 800)
    student_facts.record_event(vault_event(2, [MARKS]))
    decision = run_rule(world, plan_id, event_id(world.engine, plan_id))
    world.replanner.accept("stu-1", decision.proposal_id)
    live = {t.programme_ref for t in task_rows(world.engine, TENANT, plan_id).values()}
    assert "p-hard" not in live and "p-easy" in live


def send(world, plan_id, version, obtained):
    world.vault["stu-1"] = facts_for("stu-1", version, obtained)
    student_facts.record_event(vault_event(version, [MARKS]))
    return run_rule(world, plan_id, event_id(world.engine, plan_id))


def test_an_improving_fact_proposes_nothing_expires_the_old_proposal_and_refreshes_the_note(world):
    plan_id = start(world)
    assert send(world, plan_id, 1, 1000).status == "applied"
    first = send(world, plan_id, 2, 800)
    assert first.status == "pending"
    again = send(world, plan_id, 3, 1000)  # the marks are back: p-hard reads likely_meets again
    assert again.status == "applied" and world.replanner.proposals.get(again.proposal_id).ops == []
    # final review I2: the earlier removal is no longer true, so it expired and cannot be accepted
    assert world.replanner.proposals.get(first.proposal_id).status == "expired"
    assert world.replanner.proposals.pending_for("stu-1") == []
    with pytest.raises(ProposalStale):
        world.replanner.accept("stu-1", first.proposal_id)
    live = [p.programme_ref for p in world.svc.plans._contract(plan_id)[0].programmes]
    assert live == ["p-easy", "p-hard"]
    N = models.eligibility_notes
    with world.engine.connect() as conn:
        notes = [(n.programme_ref, n.verdict, n.payload["previous"]) for n in conn.execute(select(N).order_by(N.c.id))]
    assert notes == [("p-hard", "likely_below", "likely_meets"), ("p-hard", "likely_meets", "likely_below")]


def test_every_programme_reading_below_escalates_and_proposes_no_removal(world):
    plan_id = start(world)
    assert send(world, plan_id, 1, 1000).status == "applied"
    decision = send(world, plan_id, 2, 100)  # about 9 percent: both fake thresholds are missed
    # R-22: when every place is affected the plan escalates; it is never emptied by one accepted proposal.
    ops = [o["op"] for o in world.replanner.proposals.get(decision.proposal_id).ops]
    assert ops == ["escalate"] and decision.status != "pending"
    assert world.replanner.proposals.pending_for("stu-1") == []
    live = [p.programme_ref for p in world.svc.plans._contract(plan_id)[0].programmes]
    assert live == ["p-easy", "p-hard"]


def test_rule_escalates_when_the_removals_would_leave_fewer_than_the_minimum():
    event = Event(1, 1, None, "student_fact_changed", {"keys": [MARKS], "vault_version": 2})
    assert rules_for(event, state(["a", "b"]), ReplanConfig()) == [Escalate(reason=REASONS["fact_all_below"])]
    two = ReplanConfig(min_programmes=2)  # one would be left, the route wants two
    assert rules_for(event, state(["b"]), two) == [Escalate(reason=REASONS["fact_all_below"])]
    assert rules_for(event, state(["b"]), ReplanConfig(min_programmes=1)) == [
        CancelProgramme(programme_ref="b", reason=REASONS["fact_below"])]


# --- the production wiring: the registered os.replan workflow ---------------------------------------------------

from tests.os.test_replan_run import ctx, P1, STUDENT, TENANT as RUN_TENANT  # noqa: E402,F401 - ctx is used by name


def _germany_gpa_change(ctx, min_pass: bool):
    """Germany, a Vault CGPA of 1.0 out of 4.0 against a 2.5 maximum German grade. With `min_pass` the student's own
    minimum-pass letter is on file (a firm verdict); without it the route default stands in (provisional)."""
    from app.os.documents.store import ProfileStore

    host = {"v": None}
    ports.configure(pytypes.SimpleNamespace(engine=ctx.engine, settings=pytypes.SimpleNamespace(tenant_id=RUN_TENANT),
                                            plans=ctx.r.plans), student_facts=lambda ref: host["v"])
    manifest.set_enabled(ctx.engine, RUN_TENANT, True)
    ctx.r.plans.knowledge.upsert("programme", P1, "grade_requirement", Fact({"german_max": 2.5}, "q", URL, NOW, 2027,
                                                                         "confirmed"), "manual")
    from app.os.eligibility.notes import refresh

    refresh(ctx.r.plans, STUDENT, ctx.plan_id)  # the first reading writes no note; the change below does
    if min_pass:
        profiles = ProfileStore(ctx.engine, RUN_TENANT)
        profiles.set(STUDENT, "min_passing_grade_letter.min_pass", 2.0, None)
        profiles.set(STUDENT, "min_passing_grade_letter.scale_best", 4.0, None)
    items = [{"key": "education.bachelor.gpa", "value": 1.0, "evidence": "stated", "vault_version": 1},
             {"key": "education.bachelor.gpa_scale", "value": 4.0, "evidence": "stated", "vault_version": 1}]
    host["v"] = StudentFactsV1.model_validate({"schema": "pai.student_facts.v1", "student_ref": STUDENT,
                                               "vault_version": 1, "built_at": NOW, "eligible_levels": None,
                                               "facts": items}).model_dump(by_alias=True)
    return ctx.run(ctx.event("student_fact_changed", keys=["education.bachelor.gpa"], vault_version=1))


def test_the_workflow_reads_the_facts_for_a_fact_change(ctx):  # noqa: F811
    """The rules step of the registered workflow passes the programmes that read below (`with_below`); without that
    the event would close with nothing to change. A firm verdict (the student's own minimum pass is on file)."""
    try:
        got = _germany_gpa_change(ctx, min_pass=True)
        assert got["status"] == "pending", got
        proposal = ctx.r.proposals.get(got["proposal_id"])
        assert proposal.big and {o["op"] for o in proposal.ops} == {"cancel_programme"}
    finally:
        ports.configure(None)


def test_a_provisional_below_verdict_shows_in_the_note_but_proposes_no_removal(ctx):  # noqa: F811
    """Final review I3 (evidence rule): the route's default minimum pass is not the student's own, so a verdict that
    stands on it only writes the labelled note."""
    try:
        got = _germany_gpa_change(ctx, min_pass=False)
        assert got["status"] == "applied" and ctx.r.proposals.pending_for(STUDENT) == []
        N = models.eligibility_notes
        with ctx.engine.connect() as conn:
            notes = [(n.programme_ref, n.verdict, n.payload["lines"]) for n in conn.execute(select(N))]
        assert [(r, v) for r, v, _ in notes if r == P1][-1] == (P1, "likely_below")
        assert any(line.get("provisional") for _, _, lines in notes for line in lines)
    finally:
        ports.configure(None)


def test_an_expiry_never_overwrites_an_answered_proposal(world):
    """The student accepted at the moment the fact improved: the proposal stays accepted and keeps its revision."""
    plan_id = start(world)
    assert send(world, plan_id, 1, 1000).status == "applied"
    first = send(world, plan_id, 2, 800)
    world.replanner.accept("stu-1", first.proposal_id)
    before = world.replanner.proposals.get(first.proposal_id)
    assert before.status == "accepted" and before.revision is not None
    assert world.replanner.proposals.expire_if_pending(first.proposal_id) is False
    after = world.replanner.proposals.get(first.proposal_id)
    assert (after.status, after.revision) == ("accepted", before.revision)
