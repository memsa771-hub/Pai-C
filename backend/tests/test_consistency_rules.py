"""Consistency rules 1-8 (P1-T10 A2, R-05, R-04): pure `check` over planted pairs, and `counsellor_side` on SQLite."""

import dataclasses
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models import OsOutbox, VaultVersion
from app.pai_c.connect import consistency as cons
from app.pai_c.connect.consistency import (
    CounsellorSide,
    DecisionView,
    Finding,
    OutboxItem,
    check,
)

pytestmark = [pytest.mark.req("R-05"), pytest.mark.req("R-04")]
NOW = datetime(2026, 11, 7, 21, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(hours=2)
YOUNG = NOW - timedelta(minutes=2)


def decision(version=1, status="chosen", supported=True, field="f_a", refs=("p1",), place_fields=()):
    return DecisionView(version, status, supported, field, tuple(refs), tuple(place_fields), OLD)


def row(version=1, status="delivered", code=None, at=OLD, kind="decision"):
    return OutboxItem(f"{kind}:ws:{version}", kind, version, status, code, at)


def plan(id=7, status="active", version=1, source="counsellor", reason=None, contract=True, export=True):
    return NS(id=id, source=source, status=status, close_reason=reason, decision_version=version,
              contract_matches_export=contract, export_hash_matches=export)


def side(**kw):
    base = {"workspace_id": "ws", "newest": decision(), "outbox": (row(),), "vault_version": 0}
    return CounsellorSide(**{**base, **kw})


def os_(**kw):
    base = {"latest_version": 1, "intake_status_by_version": {1: "planned"}, "refusal_by_version": {}, "plans": [plan()],
                "latest_vault_version": 0, "unprocessed_fact_events": [], "needed_file_refs": [], "duplicate_requests": []}
    return NS(**{**base, **kw})


def run(c, o, mode="settled", **kw):
    return check(c, o, mode=mode, now=NOW, **kw)


def only(findings, rule, *codes):
    assert findings == [Finding(rule, tuple(codes), findings[0].plan_id if findings else None)], findings


def test_a_young_pending_intake_row_is_in_flight_at_night_and_a_finding_when_settled():
    waiting = dict(intake_status_by_version={1: "pending"}, plans=[])
    c = side()  # delivered
    young = os_(**waiting, intake_pending_since_by_version={1: YOUNG})
    old = os_(**waiting, intake_pending_since_by_version={1: OLD})
    assert run(c, young, "nightly") == []
    only(run(c, old, "nightly"), 1, "no_plan")  # pending for two hours: stuck
    only(run(c, young, "settled"), 1, "no_plan")  # the end-of-test check tolerates nothing pending
    only(run(c, os_(**waiting), "nightly"), 1, "no_plan")  # an OS view without the ages: no excuse


def test_a_finished_plan_still_holds_its_decision_version():
    c = side()
    assert run(c, os_(plans=[plan(status="done")])) == [] and run(c, os_(plans=[plan(status="done")]), "nightly") == []
    only(run(c, os_(plans=[plan(status="closed")])), 1, "no_plan")  # a closed plan holds nothing


def test_an_open_plan_left_at_an_older_version_is_stale():
    """Rule 2: the OS applied version 2, but an open Counsellor plan still stands at version 1."""
    c = side(newest=decision(version=2), outbox=(row(1), row(2)))
    both = os_(latest_version=2, intake_status_by_version={1: "planned", 2: "revised"},
               plans=[plan(id=7, version=1), plan(id=8, version=2)])
    got = run(c, both)
    assert got == [Finding(2, ("plan_version_stale",), 7)]
    # not a finding while the OS has not applied the newest version (rule 1 owns that), or when it held / refused it
    assert run(c, os_(latest_version=1, intake_status_by_version={1: "planned"}, plans=[plan(id=7, version=1)]),
               ).count(Finding(2, ("plan_version_stale",), 7)) == 0
    for status in ("held", "paused", "refused"):
        o = os_(latest_version=2, intake_status_by_version={1: "planned", 2: status}, plans=[plan(id=7, version=1)])
        assert [f for f in run(c, o) if f.rule == 2] == [], status
    # a closed plan at an older version is the normal result of a replacement
    closed = os_(latest_version=2, intake_status_by_version={2: "replaced"}, plans=[plan(id=7, status="closed", version=1),
                                                                               plan(id=8, version=2)])
    assert run(c, closed) == []


def test_a_clean_pair_has_no_finding_in_either_mode():
    c, o = side(), os_()
    assert run(c, o) == [] and run(c, o, "nightly") == []


# rule 1
@pytest.mark.parametrize("o,code", [
    (os_(latest_version=None, intake_status_by_version={}, plans=[]), "no_plan"),
    (os_(plans=[]), "no_plan"),
    (os_(intake_status_by_version={1: "stale"}), "no_plan"),
    (os_(latest_version=0, intake_status_by_version={}, plans=[]), "version_behind"),
    (os_(latest_version=2, intake_status_by_version={2: "revised"}, plans=[plan(version=2)]), "version_ahead"),
])
def test_rule_1_codes(o, code):
    only(run(side(newest=decision(version=1)), o), 1, code)


def test_rule_1_a_refusal_reason_settles_it():
    o = os_(plans=[], intake_status_by_version={1: "refused"}, refusal_by_version={1: "not_authorized"})
    assert run(side(), o) == []


@pytest.mark.parametrize("status", ["planned", "revised", "replaced", "held", "paused"])
def test_rule_1_every_held_status_with_a_plan_is_fine(status):
    assert run(side(), os_(intake_status_by_version={1: status})) == []


def test_a_not_sent_row_with_a_code_is_a_recorded_refusal():
    c = side(outbox=(row(status="not_sent", code="incomplete"),))
    assert run(c, os_(latest_version=None, intake_status_by_version={}, plans=[])) == []
    c = side(outbox=(row(status="not_sent", code=None),))
    only(run(c, os_(latest_version=None, intake_status_by_version={}, plans=[])), 1, "no_plan")


def test_nightly_treats_young_pending_work_as_in_flight():
    gone = os_(latest_version=None, intake_status_by_version={}, plans=[])
    assert run(side(outbox=(row(status="pending", at=YOUNG),)), gone, "nightly") == []
    only(run(side(outbox=(row(status="pending", at=OLD),)), gone, "nightly"), 1, "no_plan")
    c = side(vault_version=3, outbox=(row(), row(3, "pending", None, YOUNG, "vault_event")))
    assert run(c, os_(latest_vault_version=2), "nightly") == []
    ev = os_(latest_vault_version=3, unprocessed_fact_events=[30.0])
    assert run(c, ev, "nightly") == []
    assert run(c, os_(latest_vault_version=3, unprocessed_fact_events=[NS(age_seconds=5000)]), "nightly")


def test_settled_tolerates_nothing_pending():
    gone = os_(latest_version=None, intake_status_by_version={}, plans=[])
    only(run(side(outbox=(row(status="pending", at=YOUNG),)), gone, "settled"), 1, "no_plan")
    c = side(vault_version=3, outbox=(row(), row(3, "pending", None, YOUNG, "vault_event")))
    only(run(c, os_(latest_vault_version=2), "settled"), 5, "vault_behind")
    only(run(c, os_(latest_vault_version=3, unprocessed_fact_events=[1.0]), "settled"), 5, "replan_pending")


def test_withdrawn_then_rechosen_checks_only_the_newest_version():
    # versions 1 chosen, 2 withdrawn, 3 chosen again: only version 3 is asked of the OS
    c = side(newest=decision(version=3), outbox=(row(1), row(2), row(3)))
    o = os_(latest_version=3, intake_status_by_version={1: "planned", 2: "withdrawn", 3: "planned"},
            plans=[plan(1, "closed", 1, reason="withdrawn:x"), plan(9, "active", 3)])
    assert run(c, o) == []


# rule 2
def test_rule_2_codes():
    only(run(side(), os_(plans=[plan(contract=False)])), 2, "contract_hash")
    only(run(side(), os_(plans=[plan(export=False)])), 2, "export_hash")
    assert run(side(), os_(plans=[plan(contract=False, export=False)])) == [
        Finding(2, ("contract_hash", "export_hash"), 7)]
    only(run(side(newest=None, outbox=()), os_(latest_version=None, intake_status_by_version={})), 2,
         "plan_without_decision")


def test_rule_2_ignores_closed_plans_and_other_sources():
    o = os_(plans=[plan(), plan(8, "closed", contract=False), plan(9, source="self", contract=False)])
    assert run(side(), o) == []


# rule 3
def test_rule_3():
    c = side(newest=decision(2, "withdrawn"), outbox=(row(), row(2)))
    closed = [plan(status="closed", reason="withdrawn:x")]
    assert run(c, os_(latest_version=2, intake_status_by_version={2: "withdrawn"}, plans=closed)) == []
    only(run(c, os_(latest_version=2, plans=[plan()])), 3, "plan_not_stopped")
    pending = side(newest=decision(2, "withdrawn"), outbox=(row(), row(2, "pending", None, YOUNG)))
    assert run(pending, os_(plans=[plan()]), "nightly") == []


# rule 4
def test_rule_4_codes():
    only(run(side(ticked_supported_versions=(1,)), os_()), 4, "checklist_ticked")
    c = side(newest=decision(supported=False), outbox=(row(status="not_sent", code="not_supported"),))
    only(run(c, os_()), 4, "plan_for_unsupported")
    only(run(side(roadmap_kind="checklist"), os_()), 4, "checklist_served")
    assert run(side(roadmap_kind="os"), os_()) == [] and run(side(roadmap_kind=None), os_()) == []


def test_unsupported_route_needs_no_plan_and_forbids_one():
    c = side(newest=decision(supported=False), outbox=(row(status="not_sent", code="not_supported"),))
    nothing = os_(latest_version=None, intake_status_by_version={}, plans=[])
    assert run(c, nothing) == []
    assert run(c, os_(plans=[plan(status="closed")])) == []
    assert [f.rule for f in run(c, os_())] == [4]


# rule 5
def test_rule_5_codes():
    c = side(vault_version=4)
    assert run(c, os_(latest_vault_version=4)) == [] and run(c, os_(latest_vault_version=5)) == []
    only(run(c, os_(latest_vault_version=3)), 5, "vault_behind")
    only(run(c, os_(latest_vault_version=4, unprocessed_fact_events=[9])), 5, "replan_pending")
    assert run(side(vault_version=0), os_(latest_vault_version=None)) == []


# rule 6
def test_rule_6_codes():
    c = side(live_file_ids=frozenset({"a"}), trashed_file_ids=frozenset({"t"}))
    assert run(c, os_(needed_file_refs=["a"])) == []
    only(run(c, os_(needed_file_refs=["a", "gone"])), 6, "file_missing")
    only(run(c, os_(needed_file_refs=["t"])), 6, "file_trashed")
    assert run(c, os_(needed_file_refs=["gone", "t"])) == [Finding(6, ("file_missing", "file_trashed"))]


# rule 7
def test_rule_7():
    only(run(side(), os_(duplicate_requests=[NS()])), 7, "duplicate_request")


# rule 8
def test_rule_8_codes():
    ex = ("f_x",)
    assert run(side(excluded_fields=ex), os_()) == []
    only(run(side(excluded_fields=ex, newest=decision(field="f_x")), os_()), 8, "in_choice")
    only(run(side(excluded_fields=ex, newest=decision(place_fields=("f_x",))), os_()), 8, "in_places")
    only(run(side(excluded_fields=ex, stage_h_fields=("f_x",)), os_()), 8, "in_stage_h")
    only(run(side(excluded_fields=ex, path_fields=("f_x",)), os_()), 8, "in_paths")
    both = run(side(excluded_fields=ex, newest=decision(field="f_x"), path_fields=("f_x",)), os_())
    assert both == [Finding(8, ("in_choice", "in_paths"))]


def test_rule_8_ignores_a_withdrawn_choice():
    c = side(excluded_fields=("f_x",), newest=decision(2, "withdrawn", field="f_x"),
             outbox=(row(), row(2, "delivered")))
    assert run(c, os_(latest_version=2, plans=[plan(status="closed")])) == []


def test_rules_skip_while_their_part_is_off():
    c = side(newest=None, outbox=(), ticked_supported_versions=(1,), vault_version=2, excluded_fields=("f",),
             stage_h_fields=("f",))
    o = os_(plans=[plan()], latest_version=None, intake_status_by_version={}, latest_vault_version=0,
            needed_file_refs=["x"], duplicate_requests=[NS()])
    assert {f.rule for f in run(c, o)} == {2, 4, 5, 6, 7, 8}
    assert {f.rule for f in run(c, o, parts=frozenset())} == set()
    assert {f.rule for f in run(c, o, parts={"CONNECT_HANDOFF"})} == {2, 8}
    assert {f.rule for f in run(c, o, parts={"CONNECT_STUDENT_FACTS"})} == {5, 7}
    assert {f.rule for f in run(c, o, parts={"CONNECT_ONE_UPLOAD"})} == {6}
    assert {f.rule for f in run(c, o, parts={"CONNECT_ROADMAP_FROM_PLANVIEW"})} == {4}


def test_check_rejects_an_unknown_mode():
    with pytest.raises(ValueError):
        check(side(), os_(), mode="weekly", now=NOW)


# the Counsellor side
def test_counsellor_side_reads_no_vault_value():
    kinds = {f.name: f.type for f in dataclasses.fields(CounsellorSide)}
    assert not {"vault", "facts", "values", "value", "memory"} & set(kinds)
    assert not [n for n in kinds if "text" in n or "sentence" in n]
    for cls in (DecisionView, OutboxItem, Finding):
        assert not [f.name for f in dataclasses.fields(cls) if "payload" in f.name or "text" in f.name]


@pytest.mark.asyncio
async def test_counsellor_side_on_sqlite_with_a_real_decision_and_outbox():
    from app.models import FileRecord
    from app.pai_c.roadmap.decisions import RouteDecisionService
    from tests.test_decision_outbox import DETAILS, on
    from tests.test_route_journey import confirmed_student, with_routes

    async with confirmed_student() as (_, student, db, _journey):
        with_routes(student, db)
        ws = student.workspace_id
        empty = cons.counsellor_side(db, ws)
        assert empty.newest is None and empty.outbox == () and empty.export is None and empty.vault_version == 0
        service = RouteDecisionService(db)
        with on(), patch("app.pai_os_bridge.route_supported", return_value=True):
            service.choose(ws, "electrical_engineering", details=DETAILS)
            db.commit()
        db.add(VaultVersion(workspace_id=ws, version=3, key_versions={"education.level": 3}))
        db.add(OsOutbox(workspace_id=ws, kind="vault_event", key=f"vault_event:{ws}:3", status="pending",
                        payload={"keys": ["education.level"]}))
        db.add_all([FileRecord(id="live1", workspace_id=ws, filename="a.pdf", size=1, storage_key="k1",
                               uploaded_by="human:user"),
                    FileRecord(id="gone1", workspace_id=ws, filename="b.pdf", size=1, storage_key="k2",
                               uploaded_by="human:user", status="deleted")])
        db.commit()
        c = cons.counsellor_side(db, ws)
        assert c.newest.version == 1 and c.newest.status == "chosen" and c.newest.os_supported is True
        assert c.newest.field_key == "electrical_engineering" and c.newest.place_refs == ("uni-a:cs", "uni-b:cs")
        assert [(i.kind, i.version, i.status) for i in c.outbox] == [("decision", 1, "pending"),
                                                                     ("vault_event", 3, "pending")]
        assert c.export["decision_version"] == 1 and c.export["student_ref"] == ws
        assert c.vault_version == 3 and c.live_file_ids == {"live1"} and c.trashed_file_ids == {"gone1"}
        assert c.excluded_fields == () and c.roadmap_kind is None and c.ticked_supported_versions == ()
        # the same state through the rules: the OS has not heard yet
        gone = os_(latest_version=None, intake_status_by_version={}, plans=[], latest_vault_version=0,
                   needed_file_refs=["live1", "gone1"])
        got = check(c, gone, mode="settled", now=datetime.now(timezone.utc))
        assert [(f.rule, f.codes) for f in got] == [(1, ("no_plan",)), (5, ("vault_behind",)),
                                                    (6, ("file_trashed",))]
        assert check(c, gone, mode="nightly", now=datetime.now(timezone.utc),
                     parts={"CONNECT_HANDOFF", "CONNECT_STUDENT_FACTS"}) == []
        assert len(db.scalars(select(OsOutbox)).all()) == 2  # reads only
