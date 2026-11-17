"""P1-T1: the v2 contracts beside the frozen v1 files (P1 spec §3.9, R-41). Fictional data."""

import pytest
from pydantic import ValidationError

from app.os.contracts.decision_record import DecisionRecordV1
from app.os.contracts.decision_record_v2 import DecisionRecordV2
from app.os.contracts.route_contract_v2 import RouteContractV2

pytestmark = pytest.mark.req("R-41")


def export_v2(**over) -> dict:
    base = {"schema": "pai.decision_record.v2", "decision_id": "d-1", "journey_id": "j-1", "student_ref": "ws-1",
            "decision_version": 1, "status": "chosen",
            "chosen_at": "2027-01-10T09:00:00+05:00", "authorized_at": "2027-01-10T09:01:00+05:00",
            "origin_country": "PK", "destination_country": "DE", "level": "master", "os_supported": True,
            "target_intake": {"term": "winter", "year": 2027},
            "programmes": [{"programme_ref": "prog-a", "rank": 1}, {"programme_ref": "prog-b", "rank": 2}]}
    return {**base, **over}


def test_v2_accepts_intermediate_v1_rejects_it():
    assert DecisionRecordV2.model_validate(export_v2(level="intermediate")).level == "intermediate"
    v1 = {k: v for k, v in export_v2(level="intermediate").items()
          if k not in ("decision_version", "status", "os_supported")}
    with pytest.raises(ValidationError):
        DecisionRecordV1.model_validate({**v1, "schema": "pai.decision_record.v1"})


def test_withdrawn_needs_no_places_or_intake():
    d = DecisionRecordV2.model_validate(export_v2(status="withdrawn", programmes=[], target_intake=None))
    with pytest.raises(ValueError):
        d.to_route_contract()


def test_chosen_supported_needs_places_and_intake():
    with pytest.raises(ValidationError):
        DecisionRecordV2.model_validate(export_v2(programmes=[]))
    with pytest.raises(ValidationError):
        DecisionRecordV2.model_validate(export_v2(target_intake=None))


def test_chosen_unsupported_allows_no_places():
    d = DecisionRecordV2.model_validate(export_v2(os_supported=False, programmes=[]))
    assert d.programmes == []
    with pytest.raises(ValueError):
        d.to_route_contract()


def test_places_unique_and_ranked():
    dup = [{"programme_ref": "a", "rank": 1}, {"programme_ref": "a", "rank": 2}]
    with pytest.raises(ValidationError, match="duplicate programme"):
        DecisionRecordV2.model_validate(export_v2(programmes=dup))
    gap = [{"programme_ref": "a", "rank": 1}, {"programme_ref": "b", "rank": 3}]
    with pytest.raises(ValidationError, match="ranks must be 1..n"):
        DecisionRecordV2.model_validate(export_v2(programmes=gap))
    six = [{"programme_ref": f"p{n}", "rank": n} for n in range(1, 7)]
    with pytest.raises(ValidationError, match="at most 5"):
        DecisionRecordV2.model_validate(export_v2(programmes=six))


def test_version_starts_at_one():
    with pytest.raises(ValidationError):
        DecisionRecordV2.model_validate(export_v2(decision_version=0))


def test_route_contract_v2_from_decision():
    d = DecisionRecordV2.model_validate(export_v2(level="intermediate", origin_country="pk", destination_country="pk"))
    c = d.to_route_contract()
    assert isinstance(c, RouteContractV2)
    assert (c.contract_version, c.source, c.level) == ("2", "counsellor", "intermediate")
    assert c.external_ref == "j-1:PK:intermediate"
    assert c.dedupe_key == "counsellor:j-1:PK:intermediate:2"


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError, match="Extra inputs"):
        DecisionRecordV2.model_validate(export_v2(truth_map={}))


# ---- Task 2: escalation.v2 and plan_view.v1 ----

from app.os.contracts.escalation_v2 import EscalationV2  # noqa: E402
from app.os.contracts.plan_view import PlanStep, PlanViewV1  # noqa: E402
from app.os.kernel.states import TaskState  # noqa: E402


def escalation_v2(**over) -> dict:
    base = {"schema": "pai.escalation.v2", "key": "escalation:1", "case_id": 1, "journey_id": "j-1",
            "student_ref": "ws-1", "reason": "blocking_gap", "note": "A fixed sentence.",
            "raised_at": "2027-01-10T09:00:00+00:00", "decision_version": 2}
    return {**base, **over}


def test_escalation_v2_keeps_five_reasons():
    for reason in ("not_eligible", "all_rejected", "deadline_passed", "blocking_gap", "other"):
        assert EscalationV2.model_validate(escalation_v2(reason=reason)).reason == reason
    with pytest.raises(ValidationError, match="reason"):
        EscalationV2.model_validate(escalation_v2(reason="route_not_possible"))
    assert EscalationV2.model_validate(escalation_v2(decision_version=None)).decision_version is None
    with pytest.raises(ValidationError):
        EscalationV2.model_validate(escalation_v2(decision_version=0))


def plan_view(**over) -> dict:
    base = {"schema": "pai.plan_view.v1", "student_ref": "ws-1", "state": "empty", "state_reason": None,
            "plan_id": None, "decision_version": None, "revision": None, "route": None, "pages": [],
            "consent": None, "steps": [], "requests": [], "documents_needed": [], "changes": [],
            "proposals_waiting": 0}
    return {**base, **over}


ROUTE = {"route_key": "germany_master", "origin_country": "PK", "destination_country": "DE", "level": "master",
         "target_intake": {"term": "winter", "year": 2027}}


def test_plan_view_empty_state():
    assert PlanViewV1.model_validate(plan_view()).state == "empty"
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate(plan_view(plan_id=1))
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate(plan_view(state="active", route=ROUTE, revision=1))
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate(plan_view(state="active", plan_id=1, revision=1))  # no route
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate(plan_view(state="active", plan_id=1, route=ROUTE))  # no revision
    assert PlanViewV1.model_validate(plan_view(state="active", plan_id=1, route=ROUTE, revision=1)).plan_id == 1


def test_plan_view_state_reason_only_when_paused_or_stopped():
    ok = plan_view(state="stopped", plan_id=1, route=ROUTE, revision=2, state_reason="withdrawn")
    assert PlanViewV1.model_validate(ok).state_reason == "withdrawn"
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate({**ok, "state": "active"})


def test_plan_view_codes_not_text():
    base = plan_view(state="active", plan_id=1, route=ROUTE, revision=1)
    step = {"task_id": 1, "instance_key": "k", "template_key": "t", "title": "Do it", "owner": "student",
            "status": "blocked", "blocked_reason": "waiting_on_marks", "inbox_kind": None, "programme_ref": None,
            "due_at": None, "due_tz": None, "depends_on": [], "provisional": False, "estimated": False,
            "needs": []}
    assert PlanViewV1.model_validate({**base, "steps": [step]}).steps[0].blocked_reason == "waiting_on_marks"
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate({**base, "steps": [{**step, "blocked_reason": "waiting on marks"}]})
    change = {"revision": 1, "at": "2027-01-10T09:00:00+00:00", "cause": "counsellor", "kind": "added",
              "instance_key": None}
    assert PlanViewV1.model_validate({**base, "changes": [change]}).changes[0].cause == "counsellor"
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate({**base, "changes": [{**change, "cause": "Counsellor said so"}]})


def test_plan_view_step_status_matches_kernel():
    literal = PlanStep.model_json_schema()["properties"]["status"]["enum"]
    assert set(literal) == {s.value for s in TaskState}


# ---- Task 3: os_event, choice_request, student_facts, vault_event ----

from app.os.contracts.choice_request import ChoiceRequestV1  # noqa: E402
from app.os.contracts.student_facts import StudentFactsV1  # noqa: E402
from app.os.contracts.vault_event import VaultEventV1  # noqa: E402


def choice_request(**over) -> dict:
    base = {"schema": "pai.choice_request.v1", "key": "choice:1", "student_ref": "ws-1", "journey_id": "j-1",
            "proposal_id": 1, "based_on_version": 1, "programmes": None, "target_intake": None,
            "requested_at": "2027-01-10T09:00:00+00:00"}
    return {**base, **over}


def test_choice_request_needs_a_change():
    with pytest.raises(ValidationError):
        ChoiceRequestV1.model_validate(choice_request())
    ok = ChoiceRequestV1.model_validate(choice_request(target_intake={"term": "summer", "year": 2028}))
    assert ok.programmes is None


def test_choice_request_places_ranked():
    with pytest.raises(ValidationError, match="ranks must be 1..n"):
        ChoiceRequestV1.model_validate(choice_request(programmes=[{"programme_ref": "a", "rank": 2}]))
    with pytest.raises(ValidationError):
        ChoiceRequestV1.model_validate(choice_request(programmes=[]))
    ok = ChoiceRequestV1.model_validate(choice_request(programmes=[{"programme_ref": "a", "rank": 1}]))
    assert ok.programmes[0].programme_ref == "a"


def facts(*items, **over) -> dict:
    base = {"schema": "pai.student_facts.v1", "student_ref": "ws-1", "vault_version": 3,
            "built_at": "2027-01-10T09:00:00+00:00", "eligible_levels": ["intermediate"], "facts": list(items)}
    return {**base, **over}


def fact(key="marks.total", evidence="stated", value=800) -> dict:
    return {"key": key, "value": value, "evidence": evidence, "vault_version": 2}


def test_student_facts_unique_keys():
    assert len(StudentFactsV1.model_validate(facts(fact(), fact("education.level", value="x"))).facts) == 2
    with pytest.raises(ValidationError, match="duplicate fact key"):
        StudentFactsV1.model_validate(facts(fact(), fact()))


def test_student_fact_inferred_is_not_an_evidence_level():
    assert StudentFactsV1.model_validate(facts(fact(evidence="unknown", value=None))).facts[0].value is None
    with pytest.raises(ValidationError):
        StudentFactsV1.model_validate(facts(fact(evidence="inferred")))


def test_vault_event_needs_keys():
    base = {"schema": "pai.vault_event.v1", "key": "vault:1", "student_ref": "ws-1", "vault_version": 4,
            "kind": "student_fact_changed", "keys": ["marks.total"], "at": "2027-01-10T09:00:00+00:00"}
    assert VaultEventV1.model_validate(base).keys == ["marks.total"]
    with pytest.raises(ValidationError):
        VaultEventV1.model_validate({**base, "keys": []})
    with pytest.raises(ValidationError):
        VaultEventV1.model_validate({**base, "keys": ["Marks Total"]})


# ---- Fix round 1 ----

from app.os.contracts.os_event import OsEventV1  # noqa: E402


def test_plan_route_countries_are_iso():
    bad = {**ROUTE, "destination_country": "XYZ"}
    with pytest.raises(ValidationError, match="two-letter"):
        PlanViewV1.model_validate(plan_view(state="active", plan_id=1, route=bad, revision=1))
    ok = {**ROUTE, "destination_country": "de", "origin_country": "pk"}
    v = PlanViewV1.model_validate(plan_view(state="active", plan_id=1, route=ok, revision=1))
    assert (v.route.origin_country, v.route.destination_country) == ("PK", "DE")


def test_plan_view_versions_start_at_one():
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate(plan_view(state="active", plan_id=1, route=ROUTE, revision=0))
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate(plan_view(state="active", plan_id=1, route=ROUTE, revision=1, decision_version=0))
    change = {"revision": 0, "at": "2027-01-10T09:00:00+00:00", "cause": "counsellor", "kind": "added",
              "instance_key": None}
    with pytest.raises(ValidationError):
        PlanViewV1.model_validate(plan_view(state="active", plan_id=1, route=ROUTE, revision=1, changes=[change]))


def test_os_event_rejects_unknown_kind_and_zero_version():
    base = {"schema": "pai.os_event.v1", "key": "e:1", "student_ref": "ws-1", "plan_id": 1, "decision_version": 1,
            "kind": "step_done", "instance_key": None, "at": "2027-01-10T09:00:00+00:00"}
    assert OsEventV1.model_validate(base).kind == "step_done"
    with pytest.raises(ValidationError):
        OsEventV1.model_validate({**base, "kind": "plan_exploded"})
    with pytest.raises(ValidationError):
        OsEventV1.model_validate({**base, "decision_version": 0})


def test_choice_request_duplicate_ref_rejected():
    dup = [{"programme_ref": "a", "rank": 1}, {"programme_ref": "a", "rank": 2}]
    with pytest.raises(ValidationError, match="duplicate programme"):
        ChoiceRequestV1.model_validate(choice_request(programmes=dup))


def test_guardian_required_defaults_false():
    assert DecisionRecordV2.model_validate(export_v2()).guardian_required is False


# ---- Final-review fix wave ----


def test_fact_source_and_date_optional():
    f = StudentFactsV1.model_validate(facts({**fact(evidence="shown"), "document_ref": "doc-1",
                                             "as_of": "2027-01-09T10:00:00+00:00"})).facts[0]
    assert f.document_ref == "doc-1" and f.as_of is not None
    plain = StudentFactsV1.model_validate(facts(fact())).facts[0]
    assert plain.document_ref is None and plain.as_of is None
    with pytest.raises(ValidationError, match="timezone"):
        StudentFactsV1.model_validate(facts({**fact(), "as_of": "2027-01-09T10:00:00"}))


def test_eligible_levels_unknown_and_unique():
    assert StudentFactsV1.model_validate(facts(eligible_levels=None)).eligible_levels is None
    with pytest.raises(ValidationError, match="duplicate level"):
        StudentFactsV1.model_validate(facts(eligible_levels=["master", "master"]))


def test_unknown_fact_has_no_value():
    with pytest.raises(ValidationError, match="unknown fact has no value"):
        StudentFactsV1.model_validate(facts(fact(evidence="unknown", value=5)))


def test_fact_version_cannot_exceed_top_level():
    with pytest.raises(ValidationError, match="cannot exceed"):
        StudentFactsV1.model_validate(facts({**fact(), "vault_version": 4}))  # top-level is 3
    assert StudentFactsV1.model_validate(facts({**fact(), "vault_version": 3})).facts[0].vault_version == 3


def test_fact_dict_value_may_hold_a_list():
    v = {"scope": "local", "regions": ["code_a"]}
    assert StudentFactsV1.model_validate(facts(fact("constraint.scope", value=v))).facts[0].value == v


def test_vault_event_kind_is_student_fact_changed():
    base = {"schema": "pai.vault_event.v1", "key": "vault:1", "student_ref": "ws-1", "vault_version": 4,
            "kind": "fact_changed", "keys": ["marks.total"], "at": "2027-01-10T09:00:00+00:00"}
    with pytest.raises(ValidationError):
        VaultEventV1.model_validate(base)
    assert VaultEventV1.model_validate({**base, "kind": "student_fact_changed"}).kind == "student_fact_changed"


def test_plan_view_state_reason_paused_ok_active_not():
    paused = plan_view(state="paused", plan_id=1, route=ROUTE, revision=1, state_reason="waiting_guardian")
    assert PlanViewV1.model_validate(paused).state_reason == "waiting_guardian"
    with pytest.raises(ValidationError, match="state_reason only"):
        PlanViewV1.model_validate({**paused, "state": "active"})


def test_empty_plan_view_holds_nothing():
    req = {"request_id": 1, "need": {"kind": "fact", "ref": "marks.total", "evidence": "stated"},
           "status": "open", "due_at": None, "due_tz": None}
    with pytest.raises(ValidationError, match="empty plan view"):
        PlanViewV1.model_validate(plan_view(requests=[req]))
    with pytest.raises(ValidationError, match="empty plan view"):
        PlanViewV1.model_validate(plan_view(documents_needed=[{"doc_type": "transcript", "status": "missing"}]))
    with pytest.raises(ValidationError, match="empty plan view"):
        PlanViewV1.model_validate(plan_view(route=ROUTE))


# ---- P1-T7 Task 3: fact_proposal ----

from app.os.contracts.fact_proposal import FactProposalV1  # noqa: E402


def fact_proposal(**over) -> dict:
    base = {"schema": "pai.fact_proposal.v1", "key": "fact_proposal:1:1", "student_ref": "ws-1",
            "document_ref": "file-1", "doc_type": "hssc_certificate", "confirmed_at": "2027-01-10T09:00:00+00:00",
            "facts": [{"key": "education.intermediate.marks_obtained", "value": 900}]}
    return {**base, **over}


@pytest.mark.req("R-16")
def test_fact_proposal_valid_and_strict():
    ok = FactProposalV1.model_validate(fact_proposal())
    assert ok.facts[0].value == 900
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate(fact_proposal(extra="x"))  # extra="forbid"
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate(fact_proposal(facts=[{"key": "education.x", "value": 1, "note": "n"}]))
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate(fact_proposal(confirmed_at="2027-01-10T09:00:00"))  # must be aware


@pytest.mark.req("R-16")
def test_fact_proposal_facts_bounded_and_unique():
    one = {"key": "education.intermediate.marks_obtained", "value": 1}
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate(fact_proposal(facts=[]))
    with pytest.raises(ValidationError, match="duplicate"):
        FactProposalV1.model_validate(fact_proposal(facts=[one, one]))
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate(fact_proposal(facts=[{"key": f"a.k{i}", "value": 1} for i in range(21)]))
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate(fact_proposal(facts=[{"key": "Bad Key", "value": 1}]))
    with pytest.raises(ValidationError):
        FactProposalV1.model_validate(fact_proposal(key="Fact Proposal"))


# ---- P1-T8 Task 4: fact_conflicts ----

from app.os.contracts.fact_conflicts import FactConflictsV1  # noqa: E402


def _side(side, value, evidence="stated", **over):
    return {"side": side, "value": value, "evidence": evidence, "document_ref": None, "as_of": None, **over}


def fact_conflicts(**over) -> dict:
    conflict = {"ref": "profile_issue:abc-123", "key": "education.bachelor.gpa",
                "values": [_side("current", 3.4), _side("proposed", 3.2, "shown", document_ref="file-1")],
                "answers": ["keep_current", "accept_proposed", "provide_new"]}
    base = {"schema": "pai.fact_conflicts.v1", "student_ref": "ws-1", "vault_version": 3,
            "built_at": "2027-01-10T09:00:00+00:00", "conflicts": [conflict]}
    return {**base, **over}


@pytest.mark.req("R-21")
def test_contract_rejects_extra_and_needs_two_values():
    ok = FactConflictsV1.model_validate(fact_conflicts())
    assert ok.conflicts[0].values[1].document_ref == "file-1"
    one = fact_conflicts()["conflicts"][0]
    for bad in (
        {**one, "extra": "x"},  # extra="forbid"
        {**one, "values": one["values"][:1]},  # needs two values
        {**one, "values": [*one["values"], _side("current", 1)]},  # and no more
        {**one, "values": [_side("current", 3.4), _side("current", 3.2)]},  # one of each side
        {**one, "values": [_side("current", 3.4), _side("proposed", None)]},  # a value is needed
        {**one, "values": [_side("current", 3.4), {**_side("proposed", 3.2), "note": "n"}]},
        {**one, "ref": "finding:1"},  # only a Vault card
        {**one, "key": "Full Name"},  # a fact key
        {**one, "answers": []},
        {**one, "answers": ["both_true"]},  # the OS offers three answers
        {**one, "answers": ["keep_current", "keep_current"]},
    ):
        with pytest.raises(ValidationError):
            FactConflictsV1.model_validate(fact_conflicts(conflicts=[bad]))
    with pytest.raises(ValidationError):
        FactConflictsV1.model_validate(fact_conflicts(extra="x"))
    with pytest.raises(ValidationError):
        FactConflictsV1.model_validate(fact_conflicts(built_at="2027-01-10T09:00:00"))  # must be aware
    with pytest.raises(ValidationError, match="duplicate"):
        FactConflictsV1.model_validate(fact_conflicts(conflicts=[one, one]))
