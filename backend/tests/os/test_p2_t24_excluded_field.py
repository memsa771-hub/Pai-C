# ruff: noqa: F811
"""P2-T24 (master R-15, OS side): an excluded field leaves the OS programme list, and a planned place in it becomes a
proposal, never a silent removal. The excluded fields are the Vault's: the OS reads them through StudentFacts and
stores none. Fictional programmes on the fake routes, invented marks and synthetic field codes only. No model call."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import String, cast, select, update

from app.os import models
from app.os.contracts.route_contract import IntakeRef
from app.os.contracts.student_facts import StudentFactsV1
from app.os.knowledge import fields
from app.os.ports import plan_query, student_facts
from app.os.replan.checks import task_rows
from app.os.replan.config import ReplanConfig
from app.os.replan.events import Event
from app.os.replan.ops import CancelProgramme, Escalate
from app.os.replan.rules import REASONS, PlanState, rules_for
from tests.os.test_p2_merit_ports import HOST, INTAKE, world as list_world  # noqa: F401
from tests.os.test_student_fact_replan import (  # noqa: F401
    ENTRY, MARKS, TOTAL, event_id, run_rule, start, vault_event, world,
)

pytestmark = pytest.mark.req("R-15")
AT = datetime(2026, 11, 1, tzinfo=UTC)
CODE = "zz_field_t24"  # a synthetic study-field code (the Counsellor's codes look like `pharm_d`)
KEY = fields.EXCLUDED_KEY


def tag(engine, ref, field) -> None:
    """Sets a programme's registry `field` directly (the import does it through `link_programme`)."""
    with engine.begin() as conn:
        conn.execute(update(models.programmes).where(models.programmes.c.ref == ref).values(field=field))


def facts(student, version, excluded, obtained=1000) -> dict:
    items = [{"key": MARKS, "value": obtained, "evidence": "stated", "vault_version": version},
             {"key": TOTAL, "value": 1100, "evidence": "stated", "vault_version": version},
             {"key": ENTRY, "value": 80, "evidence": "stated", "vault_version": version},
             {"key": KEY, "value": list(excluded), "evidence": "stated", "vault_version": version}]
    return StudentFactsV1.model_validate({"schema": "pai.student_facts.v1", "student_ref": student,
                                          "vault_version": version, "built_at": AT, "eligible_levels": None,
                                          "facts": items}).model_dump(by_alias=True)


def exclude(world, plan_id, version, excluded, obtained=1000):
    """The Vault now says `excluded`: one Vault event, then the replan rules and the decision."""
    world.vault["stu-1"] = facts("stu-1", version, excluded, obtained)
    student_facts.record_event(vault_event(version, [KEY]))
    return run_rule(world, plan_id, event_id(world.engine, plan_id))


def refs(listing) -> list[str]:
    return [p.programme_ref for p in listing.programmes]


# --- pure parts ------------------------------------------------------------------------------------------------------

def test_field_codes_and_the_excluded_fact():
    assert fields.field_code(None) is None and fields.field_code("  ") is None  # an empty field means nothing
    assert fields.field_code(" pharm_d ") == "pharm_d"  # a Counsellor code is used as it is
    assert fields.is_excluded("pharm_d", {"pharm_d"}) and not fields.is_excluded("", {"pharm_d"})
    assert not fields.is_excluded(None, {"pharm_d"}) and not fields.is_excluded("mbbs", {"pharm_d"})
    got = StudentFactsV1.model_validate(facts("s", 1, ["pharm_d", "law"]))
    assert fields.excluded_of(got) == {"pharm_d", "law"}
    unknown = StudentFactsV1.model_validate({**facts("s", 1, []), "facts": [
        {"key": KEY, "value": None, "evidence": "unknown", "vault_version": 0}]})
    assert fields.excluded_of(unknown) == frozenset()


def test_the_field_code_file_is_data_and_holds_only_codes(tmp_path):
    path = tmp_path / "codes.yaml"
    path.write_text("version: 1\naliases: {Some Label: some_code}\n", encoding="utf-8")
    assert fields._aliases.__wrapped__(path) == {"Some Label": "some_code"}
    path.write_text("version: 1\naliases: {Some Label: Not A Code}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fields._aliases.__wrapped__(path)
    assert isinstance(fields._aliases(), dict)  # the shipped file loads


def _state(programmes, excluded=(), below=()):
    return PlanState(1, "r", list(programmes), {}, below=tuple(below), excluded=tuple(excluded))


EVENT = Event(1, 1, None, "student_fact_changed", {"keys": [KEY], "vault_version": 2})


def test_the_rule_proposes_a_removal_for_an_excluded_place_and_escalates_when_none_would_be_left():
    assert rules_for(EVENT, _state(["a", "b"], excluded=["b"]), ReplanConfig()) == [
        CancelProgramme(programme_ref="b", reason=REASONS["field_excluded"])]
    assert rules_for(EVENT, _state(["a", "b"], excluded=["a", "b"]), ReplanConfig()) == [
        Escalate(reason=REASONS["fact_all_below"])]  # R-22: never fewer than the minimum, a person looks
    assert rules_for(EVENT, _state(["a", "b"], excluded=["b"], below=["b"]), ReplanConfig()) == [
        CancelProgramme(programme_ref="b", reason=REASONS["fact_below"])]  # one removal per place
    assert rules_for(EVENT, _state(["a", "b"]), ReplanConfig()) == []


# --- the OS programme list -------------------------------------------------------------------------------------------

def test_an_excluded_field_leaves_the_os_programme_list_and_an_empty_field_stays(list_world):
    tag(list_world.engine, "ie-1", CODE)
    tag(list_world.engine, "ie-2", "other_code")  # ie-3 has no field at all
    HOST["stu-1"] = facts("stu-1", 1, [CODE])
    for build in (plan_query.programme_list, plan_query.programme_list_v2):
        assert refs(build("ireland_master", INTAKE)) == ["ie-1", "ie-2", "ie-3"]  # no student: the route's list
        assert refs(build("ireland_master", INTAKE, "stu-1")) == ["ie-2", "ie-3"]  # empty field (ie-3) stays
        assert refs(build("ireland_master", INTAKE, "stu-9")) == ["ie-1", "ie-2", "ie-3"]  # the Vault knows nothing


def test_a_field_no_longer_excluded_brings_the_programme_back_to_the_list(list_world):
    tag(list_world.engine, "ie-1", CODE)
    HOST["stu-1"] = facts("stu-1", 1, [CODE])
    assert "ie-1" not in refs(plan_query.programme_list_v2("ireland_master", INTAKE, "stu-1"))
    HOST["stu-1"] = facts("stu-1", 2, [])
    assert refs(plan_query.programme_list_v2("ireland_master", INTAKE, "stu-1")) == ["ie-1", "ie-2", "ie-3"]
    assert refs(plan_query.programme_list("ireland_master", IntakeRef(term="winter", year=2027), "stu-1")) == [
        "ie-1", "ie-2", "ie-3"]


# --- the plan: a proposal, never a removal ---------------------------------------------------------------------------

def test_a_planned_place_in_an_excluded_field_becomes_a_pending_proposal_not_a_removal(world):
    tag(world.engine, "p-hard", CODE)
    plan_id = start(world)
    assert exclude(world, plan_id, 1, []).status == "applied"  # nothing excluded: nothing to do
    decision = exclude(world, plan_id, 2, [CODE])
    assert decision.status == "pending"
    proposal = world.replanner.proposals.get(decision.proposal_id)
    assert proposal.big and proposal.ops == [
        {"op": "cancel_programme", "programme_ref": "p-hard", "reason": REASONS["field_excluded"]}]
    assert [p.programme_ref for p in world.svc.plans._contract(plan_id)[0].programmes] == ["p-easy", "p-hard"]
    live = {t.programme_ref for t in world.replanner.state(plan_id).tasks.values()}
    assert "p-hard" in live  # nothing removed by itself
    assert world.replanner.excluded(plan_id) == ()  # held by the pending proposal: no second card
    world.replanner.accept("stu-1", decision.proposal_id)  # the student's yes removes it
    assert "p-hard" not in {t.programme_ref for t in task_rows(world.engine, "pai", plan_id).values()}
    later = exclude(world, plan_id, 3, [CODE, "other_code"])  # a later change: the removed place is not proposed again
    assert later.status == "applied" and world.replanner.proposals.get(later.proposal_id).ops == []


def test_an_empty_field_is_never_proposed_for_removal(world):
    plan_id = start(world)  # neither place has a field
    assert exclude(world, plan_id, 1, [CODE]).status == "applied"
    assert world.replanner.proposals.pending_for("stu-1") == []


def test_a_field_no_longer_excluded_expires_the_pending_removal(world):
    tag(world.engine, "p-hard", CODE)
    plan_id = start(world)
    first = exclude(world, plan_id, 1, [CODE])
    assert first.status == "pending"
    again = exclude(world, plan_id, 2, [])  # the student wants the field again
    assert again.status == "applied" and world.replanner.proposals.get(again.proposal_id).ops == []
    assert world.replanner.proposals.get(first.proposal_id).status == "expired"  # one tap can no longer drop it
    assert world.replanner.proposals.pending_for("stu-1") == []


def test_every_place_excluded_is_a_case_for_a_person_never_a_removal(world):
    tag(world.engine, "p-easy", CODE)
    tag(world.engine, "p-hard", CODE)
    plan_id = start(world)
    exclude(world, plan_id, 1, [CODE])
    assert world.replanner.proposals.pending_for("stu-1") == []
    assert world.replanner.support_cases.for_event(event_id(world.engine, plan_id)) is not None
    assert {t.programme_ref for t in world.replanner.state(plan_id).tasks.values()} >= {"p-easy", "p-hard"}


def test_no_student_fact_is_copied_into_the_os(world):
    """Ownership (master §4): the excluded field code is the Vault's. After the list and the replan read it, the only
    OS row that holds the code is the programme's own registry tag (OS data); no profile value, event, proposal or
    note carries it."""
    tag(world.engine, "p-hard", CODE)
    plan_id = start(world)
    exclude(world, plan_id, 1, [CODE])
    plan_query.programme_list_v2("pakistan_bs", IntakeRef(term="winter", year=2027), "stu-1")
    holders = []
    with world.engine.connect() as conn:
        for table in models.md.sorted_tables:
            for row in conn.execute(select(*[cast(c, String) for c in table.c])):
                if any(v is not None and CODE in v for v in row):
                    holders.append(table.name)
    assert set(holders) == {models.programmes.name}


# --- fix round 1 (review B1, M2): every OS list and every swap leaves out an excluded field ---------------------------

def _alternatives(world) -> None:
    """Two more places on the fake route that the student meets: `p-alt-x` in the excluded field, `p-alt-y` without a
    field. Fake merit closing and an empty entry-test rule, as for the fixture's places."""
    from app.os.knowledge import Fact, SqlKnowledge
    from app.os.knowledge.programmes import Programme, ProgrammeStore

    store, kb = ProgrammeStore(world.engine, "pai"), SqlKnowledge(world.engine, "pai")
    for ref in ("p-alt-x", "p-alt-y"):
        store.upsert(Programme(ref=ref, route_key="pakistan_bs", university="Uni X", name=ref, aliases=(),
                               start_urls=("https://uni.example/x",), official_domains=("uni.example",)))
        for name, value in (("merit_closing", {"aggregate": 50}), ("entry_test_required", {"any_of": []})):
            kb.upsert("programme", ref, name, Fact(value, "q", "https://uni.example/x", AT, 2027, "confirmed"),
                      "manual")
    tag(world.engine, "p-alt-x", CODE)


def test_a_swap_never_brings_in_a_programme_of_an_excluded_field(world):
    from app.os.replan.ops import SwapProgramme

    _alternatives(world)
    plan_id = start(world, refs=("p-hard",))
    world.vault["stu-1"] = facts("stu-1", 1, [])
    assert set(world.replanner.state(plan_id, with_suggestions=True).suggestions["p-hard"]) >= {"p-alt-x", "p-alt-y"}
    world.vault["stu-1"] = facts("stu-1", 2, [CODE])
    state = world.replanner.state(plan_id, with_suggestions=True)
    assert "p-alt-x" not in state.suggestions["p-hard"] and "p-alt-y" in state.suggestions["p-hard"]
    rejected = Event(9, plan_id, None, "admission_rejected", {"programme_ref": "p-hard"})
    (op,) = rules_for(rejected, state, ReplanConfig())  # the rejection and unanswered rules swap to these
    assert isinstance(op, SwapProgramme) and op.in_ref != "p-alt-x"


def test_the_os_route_list_and_its_suggestions_leave_out_an_excluded_field(world):
    from app.os.api import self_serve
    from app.os.eligibility.notes import refresh

    _alternatives(world)
    world.vault["stu-1"] = facts("stu-1", 1, [CODE], obtained=700)  # about 64 percent: below p-hard's fake 80
    listed = [p["ref"] for p in self_serve.route_programmes(world.svc.plans, "stu-1", "pakistan_bs", 2027)]
    assert "p-alt-x" not in listed and {"p-easy", "p-hard", "p-alt-y"} <= set(listed)  # empty fields stay
    other = [p["ref"] for p in self_serve.route_programmes(world.svc.plans, "stu-2", "pakistan_bs", 2027)]
    assert "p-alt-x" in other  # another student excluded nothing
    got = self_serve.eligibility(world.svc.plans, "stu-1", "p-hard", "pakistan_bs", 2027)
    picks = [s["programme_ref"] for s in got["suggestions"]]
    assert picks and "p-alt-x" not in picks
    world.vault["stu-1"] = facts("stu-1", 2, [CODE])  # p-hard met first: a later drop writes a note
    plan_id = start(world, refs=("p-hard",))
    refresh(world.svc.plans, "stu-1", plan_id)
    world.vault["stu-1"] = facts("stu-1", 3, [CODE], obtained=700)
    assert refresh(world.svc.plans, "stu-1", plan_id)[0] == 1  # the eligibility note, with its swap suggestions
    with world.engine.connect() as conn:
        notes = conn.execute(select(models.eligibility_notes.c.payload)).scalars().all()
    shown = [s for n in notes for s in n.get("suggestions", [])]
    assert shown and "p-alt-x" not in shown


def test_a_studentfacts_failure_leaves_the_bridge_list_unfiltered(list_world):
    """Review M2: the list falls back to the route's full list (logged); rule 8 still opens a case for a chosen
    excluded field. It never answers with no places."""
    from app import pai_os_bridge as bridge
    from app.os import ports

    tag(list_world.engine, "ie-1", CODE)

    def broken(ref):
        raise RuntimeError("host down")

    ports.configure(list_world, student_facts=broken)
    got = bridge.programmes_for("ireland_master", "winter", 2027, "stu-1")
    assert [p["ref"] for p in got] == ["ie-1", "ie-2", "ie-3"]
    assert refs(plan_query.programme_list_v2("ireland_master", INTAKE, "stu-1")) == ["ie-1", "ie-2", "ie-3"]
