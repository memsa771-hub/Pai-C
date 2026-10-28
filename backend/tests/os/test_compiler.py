from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from app.os.compiler import CompileError, compile_plan, end_of_day, needed_fields
from app.os.contracts.route_contract import RouteContract
from app.os.knowledge import Fact
from app.os.playbooks import Playbook, load_playbook

FAKE = Path(__file__).parent / "playbooks"
IE = load_playbook(FAKE / "ireland_master.v1.yaml")
TODAY = date(2027, 3, 1)
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)


def contract(refs, origin="PK", destination="IE", level="master") -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": "ext-1", "student_ref": "stu-1",
        "origin_country": origin, "destination_country": destination, "level": level,
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)],
    })


def fact(value, status="confirmed") -> Fact:
    quote, url = ("q", "https://uni.example/p") if status == "confirmed" else ("", "")
    return Fact(value=value, quote=quote, url=url, checked_at=CHECKED, intake_year=2027, status=status)


def deadlines(status="confirmed", **by_ref) -> dict:
    return {(ref, "deadline_close"): fact({"date": d}, status) for ref, d in by_ref.items()}


def task(draft, key):
    return next(t for t in draft.tasks if t.instance_key == key)


def book(**changes) -> Playbook:
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data.update(changes)
    return Playbook.model_validate(data)


def test_fan_out_and_dates():
    d = compile_plan(contract(["p1", "p2"]), IE, {}, deadlines(p1="2027-07-15", p2="2027-06-01"), TODAY)
    apply_p1 = task(d, "apply@p1")
    assert apply_p1.latest_finish == datetime(2027, 7, 15, 23, 59, 59, tzinfo=ZoneInfo("Europe/Dublin"))
    assert apply_p1.latest_start == apply_p1.latest_finish - timedelta(days=3)
    assert {t.instance_key for t in d.tasks} == {"apply@p1", "apply@p2", "visa"}
    assert set(task(d, "visa").depends_on) == {("apply@p1", True), ("apply@p2", True)}
    assert [t.instance_key for t in d.tasks] == sorted(t.instance_key for t in d.tasks)


def test_forward_pass_from_today():
    d = compile_plan(contract(["p1"]), IE, {}, deadlines(p1="2027-07-15"), TODAY)
    assert task(d, "apply@p1").earliest_start == datetime(2027, 3, 1, tzinfo=ZoneInfo("Europe/Dublin"))
    assert task(d, "visa").earliest_start == datetime(2027, 3, 4, tzinfo=ZoneInfo("Europe/Dublin"))
    assert task(d, "apply@p1").slack_days == (task(d, "apply@p1").latest_start - task(d, "apply@p1").earliest_start).days


def test_end_of_day_on_dst_change():
    eod = end_of_day(date(2027, 3, 28), "Europe/Berlin")
    assert (eod.hour, eod.minute, eod.second) == (23, 59, 59)
    assert eod.utcoffset() == timedelta(hours=2)


def test_fact_timezone_wins_over_default():
    facts = {("p1", "deadline_close"): fact({"date": "2027-07-15", "tz": "Europe/Berlin"})}
    t = task(compile_plan(contract(["p1"]), IE, {}, facts, TODAY), "apply@p1")
    assert t.due_tz == "Europe/Berlin" and t.latest_finish.utcoffset() == timedelta(hours=2)


def test_confirmed_fact_is_firm():
    d = compile_plan(contract(["p1"]), IE, {}, deadlines(p1="2027-07-15"), TODAY)
    assert not task(d, "apply@p1").provisional
    assert not [t for t in d.tasks if t.task_type == "knowledge.confirm_fact"]


def test_unconfirmed_fact_gives_provisional_and_confirm_task():
    d = compile_plan(contract(["p1"]), IE, {}, deadlines("unconfirmed", p1="2027-07-15"), TODAY)
    assert task(d, "apply@p1").provisional
    confirm = task(d, "confirm_fact@p1:deadline_close")
    assert (confirm.task_type, confirm.kind, confirm.depends_on) == ("knowledge.confirm_fact", "work", ())
    assert ("programme", "p1", "deadline_close") in task(d, "apply@p1").fact_refs


def test_programme_without_facts_blocks():
    d = compile_plan(contract(["p1"]), IE, {}, {}, TODAY)
    assert task(d, "apply@p1").blocked_reason == "fact_missing:deadline_close"
    assert task(d, "apply@p1").latest_finish is None
    assert task(d, "confirm_fact@p1:deadline_close")


def test_cycle_rejected():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][0]["depends_on"] = [{"key": "visa"}]
    with pytest.raises(CompileError, match="cycle"):
        compile_plan(contract(["p1"]), Playbook.model_validate(data), {}, deadlines(p1="2027-07-15"), TODAY)


def test_negative_slack_at_risk():
    d = compile_plan(contract(["p1"]), IE, {}, deadlines(p1="2027-02-01"), TODAY)
    assert d.at_risk and task(d, "apply@p1").slack_days < 0 and task(d, "apply@p1").critical


def test_condition_filters():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][0]["condition"] = {"fact": "application_route", "in": ["direct"]}
    pb = Playbook.model_validate(data)
    facts = {**deadlines(p1="2027-07-15", p2="2027-07-15"),
             ("p1", "application_route"): fact("uni_assist"), ("p2", "application_route"): fact("direct")}
    d = compile_plan(contract(["p1", "p2"]), pb, {}, facts, TODAY)
    keys = {t.instance_key for t in d.tasks}
    assert "apply@p1" not in keys and "apply@p2" in keys
    assert task(d, "visa").depends_on == (("apply@p2", True),)


def test_condition_on_missing_fact_counts_true_and_provisional():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][0]["condition"] = {"fact": "application_route", "in": ["direct"]}
    d = compile_plan(contract(["p1"]), Playbook.model_validate(data), {}, deadlines(p1="2027-07-15"), TODAY)
    assert task(d, "apply@p1").provisional and task(d, "confirm_fact@p1:application_route")


def test_same_input_same_output():
    args = (contract(["p1", "p2"]), IE, {}, deadlines(p1="2027-07-15"), TODAY)
    assert compile_plan(*args) == compile_plan(*args)


def test_constant_lead_time_and_estimate_flag():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["constants"] = {"lead": {"value": 56, "estimate": True, "citations": []}}
    data["tasks"][0]["lead_time"] = {"constant": "lead"}
    d = compile_plan(contract(["p1"]), Playbook.model_validate(data), {}, deadlines(p1="2027-07-15"), TODAY)
    t = task(d, "apply@p1")
    assert t.latest_finish == end_of_day(date(2027, 7, 15), "Europe/Dublin") - timedelta(days=56)
    assert t.estimated


def test_route_fact_for_non_fan_out_task():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][1]["anchor"] = {"fact": "visa_target_date"}
    pb = Playbook.model_validate(data)
    d = compile_plan(contract(["p1"]), pb, {"visa_target_date": fact({"date": "2027-09-01"})},
                     deadlines(p1="2027-07-15"), TODAY)
    assert task(d, "visa").latest_finish == end_of_day(date(2027, 9, 1), "Europe/Dublin")
    missing = compile_plan(contract(["p1"]), pb, {}, deadlines(p1="2027-07-15"), TODAY)
    assert task(missing, "confirm_fact@ireland_master:visa_target_date")


def test_disabled_type_fallback():
    skip = compile_plan(contract(["p1"]), IE, {}, deadlines(p1="2027-07-15"), TODAY,
                        disabled_types=frozenset({"student.act"}))
    assert skip.tasks == ()
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][1].update(kind="work", task_type="system.milestone", fallback="student")
    data["tasks"][1].pop("inbox_kind")
    d = compile_plan(contract(["p1"]), Playbook.model_validate(data), {}, deadlines(p1="2027-07-15"), TODAY,
                     disabled_types=frozenset({"system.milestone"}))
    visa = task(d, "visa")
    assert (visa.task_type, visa.kind, visa.inbox_kind) == ("student.act", "student", "act")


def test_needed_fields():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][1]["anchor"] = {"fact": "visa_target_date"}
    assert needed_fields(Playbook.model_validate(data)) == ({"visa_target_date"}, {"deadline_close"})


# ---- Slice 9 Task 11 (F1): a route step's date from the chosen programme's fact ------------------------------------

NOTE = "{weeks} weeks before your semester starts on {date}"


def visa_book(**anchor) -> Playbook:
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][1]["anchor"] = {"fact": "semester_start", "programme": "visa", "note": NOTE, **anchor}
    data["tasks"][1]["lead_time"] = {"days": 42}
    return Playbook.model_validate(data)


def starts(status="confirmed", **by_ref) -> dict:
    return {(ref, "semester_start"): fact({"date": d}, status) for ref, d in by_ref.items()}


def test_anchor_on_the_chosen_programme():
    """The visa date is 6 weeks (the playbook's lead time) before the semester start of the programme the visa file
    is for, and the step cites that programme's page with a plain note saying so."""
    facts = {**deadlines(p1="2027-07-15", p2="2027-07-15"), **starts(p1="2027-10-01", p2="2027-09-15")}
    d = compile_plan(contract(["p1", "p2"]), visa_book(), {}, facts, TODAY, chosen={"visa": "p1"})
    visa = task(d, "visa")
    assert visa.latest_finish == end_of_day(date(2027, 10, 1), "Europe/Dublin") - timedelta(days=42)
    assert visa.blocked_reason is None and not visa.provisional
    assert visa.citations[0] == {"source": "fact:semester_start", "url": "https://uni.example/p",
                                 "note": "6 weeks before your semester starts on 1 October 2027"}
    assert ("programme", "p1", "semester_start") in visa.fact_refs
    assert ("programme", "p2", "semester_start") not in visa.fact_refs
    assert not any(t.instance_key.startswith("confirm_fact@p2:semester") for t in d.tasks)


def test_anchor_before_a_choice_uses_the_earliest_start():
    """No programme chosen yet: the earliest semester start of the plan's programmes, provisional (it may move once
    the student's visa programme is known), and every programme's start is looked for."""
    facts = {**deadlines(p1="2027-07-15", p2="2027-07-15"), **starts(p1="2027-10-01", p2="2027-09-15")}
    visa = task(compile_plan(contract(["p1", "p2"]), visa_book(), {}, facts, TODAY), "visa")
    assert visa.latest_finish == end_of_day(date(2027, 9, 15), "Europe/Dublin") - timedelta(days=42)
    assert visa.provisional and visa.blocked_reason is None
    assert {("programme", r, "semester_start") for r in ("p1", "p2")} <= set(visa.fact_refs)
    one = task(compile_plan(contract(["p1"]), visa_book(), {}, facts, TODAY), "visa")
    assert not one.provisional  # one programme: it is the one


def test_anchor_waits_for_the_chosen_programmes_start():
    """The chosen programme has no semester start yet: the step stays blocked on it (another programme's date is
    never used for it), and the start is looked for."""
    facts = {**deadlines(p1="2027-07-15", p2="2027-07-15"), **starts(p2="2027-09-15")}
    d = compile_plan(contract(["p1", "p2"]), visa_book(), {}, facts, TODAY, chosen={"visa": "p1"})
    assert task(d, "visa").blocked_reason == "fact_missing:semester_start"
    assert task(d, "visa").latest_finish is None
    assert task(d, "confirm_fact@p1:semester_start")
    none = compile_plan(contract(["p1", "p2"]), visa_book(), {}, deadlines(p1="2027-07-15", p2="2027-07-15"), TODAY)
    assert task(none, "visa").blocked_reason == "fact_missing:semester_start"
    assert task(none, "confirm_fact@p1:semester_start") and task(none, "confirm_fact@p2:semester_start")


def test_anchor_ignores_a_removed_programme():
    """A programme the student removed (an accepted cancel_programme) is never the visa date's programme."""
    facts = {**deadlines(p1="2027-07-15", p2="2027-07-15"), **starts(p1="2027-10-01", p2="2027-09-15")}
    gone = [SimpleNamespace(op="cancel_programme", target="p2", payload={})]
    visa = task(compile_plan(contract(["p1", "p2"]), visa_book(), {}, facts, TODAY, overrides=gone), "visa")
    assert visa.latest_finish == end_of_day(date(2027, 10, 1), "Europe/Dublin") - timedelta(days=42)
    chosen_gone = compile_plan(contract(["p1", "p2"]), visa_book(), {}, facts, TODAY, overrides=gone,
                               chosen={"visa": "p2"})
    assert task(chosen_gone, "visa").latest_finish == visa.latest_finish


def test_needed_fields_with_a_programme_anchor():
    assert needed_fields(visa_book()) == (set(), {"deadline_close", "semester_start"})


def test_programme_anchor_rules():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][0]["anchor"] = {"fact": "semester_start", "programme": "visa"}  # a fanned-out step has its own
    with pytest.raises(ValueError, match="programme"):
        Playbook.model_validate(data)
    with pytest.raises(ValueError, match="placeholder"):
        visa_book(note="{month} before")


def test_germany_visa_date_from_the_semester_start():
    """F1: the Germany playbook derives the visa date from the visa programme's semester start, 6 weeks before it,
    with the number in the playbook (invariant 12); nothing anchors on visa_target_date any more."""
    gm = load_playbook(Path(__file__).parents[2] / "app/os/playbooks/germany_master.v1.yaml")
    visa = gm.task("visa_apply")
    assert (visa.anchor.fact, visa.anchor.programme) == ("semester_start", "visa")
    assert gm.constants[visa.lead_time.constant].value == 42
    assert visa.anchor.note and visa.anchor.waiting
    assert all(t.anchor is None or t.anchor.fact != "visa_target_date" for t in gm.tasks)
