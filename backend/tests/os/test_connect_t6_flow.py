"""P1-T6 Task 8 (R-07, R-08, R-09, R-11; rows 6.5, 6.6, 6.12, 6.13, 6.16, 6.17): the whole proposal, escalation,
builder and adoption flows against a real PAI OS. The Counsellor side is the real HTTP API on a student session; the OS
side is the real services behind the ports on Postgres. Germany route (the real playbook), the Vault drives the first
proposal, and the OS builder runs with the Counsellor module on and off. Fictional students and thresholds; the mailer
is stubbed; no model is called. No chat row is made at any step."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, update

from app import pai_os_bridge as bridge
from app.config import config
from app.models import RouteDecision, StudentJourney
from app.os import models, ports
from app.os.knowledge import Fact, SqlKnowledge
from app.os.ports import choice_requests
from app.pai_c.connect import (
    student_facts as host_facts,  # noqa: F401 - the bridge builds the facts
)
from app.pai_c.roadmap.decisions import RouteDecisionService
from tests.os.test_adoption_flow import own_plan, sources, tasks
from tests.os.test_api import agree
from tests.os.test_builder_choice_flow import START, count, os_client
from tests.os.test_choice_request_delivery import Flow
from tests.os.test_connect_t4_flow import run_rules, write
from tests.os.test_connect_t5_flow import (  # noqa: F401
    WINTER,
    chosen,
    germany_student,
    level,
    row_counts,
    run_os,
    svc,
    vault,
    world,
)
from tests.test_roadmap_api import TOKEN, data
from tests.test_roadmap_choice_api import choose_with
from tests.os.connect_check import assert_consistent

pytestmark = [pytest.mark.req("R-07"), pytest.mark.req("R-08"), pytest.mark.req("R-09"), pytest.mark.req("R-11")]

OVGU, BTU_AI, BTU_CYBER = "ovgu-eeit", "btu-artificial-intelligence", "btu-cyber-security"
THREE = [{"ref": OVGU, "rank": 1}, {"ref": BTU_AI, "rank": 2}, {"ref": BTU_CYBER, "rank": 3}]
CHECKED = datetime(2026, 11, 5, tzinfo=timezone.utc)
SERVICE_TOKEN = "service-token-for-the-t6-flow"
CHAT = ("events", "pai_counselor_turn_decisions", "pai_turn_plans")  # the tables a chat message or turn would grow


def chat_rows(who) -> dict[str, int]:
    """Rows a chat message or turn would make: the turn tables, and any event that is not a Vault event (the Vault
    writes of this flow log `vault.*` events, which are not chat)."""
    from app.models import Base

    events = Base.metadata.tables["events"]
    counts = row_counts(who)
    with who.factory() as db:
        counts["events"] = db.scalar(select(func.count()).select_from(events).where(~events.c.type.like("vault.%")))
    return {t: counts[t] for t in CHAT}


def no_chat(who, before: dict[str, int]) -> None:
    """Throughout (R-45): no message, turn or turn-plan row; the other tables (the Vault, the decisions, the outbox,
    the bell) may grow because the flow writes them."""
    assert chat_rows(who) == {t: before[t] for t in CHAT}


def ielts_needs(svc_, ref: str, band: float) -> None:
    """A fictional, confirmed English bar for one programme."""
    SqlKnowledge(svc_.engine, "pai").upsert("programme", ref, "english_requirement",
                                            Fact({"ielts": band}, "q", "https://uni.example/e", CHECKED, 2027,
                                                 "confirmed"), "manual")


@contextmanager
def flow(world_, places, facts=False):
    """A Germany master student with a planned choice (decision version 1), the Flow helper of the delivery tests."""
    svc_ = world_
    ports.configure(svc_, choice_enabled=bridge.choice_enabled, on_choice_request=None,
                    student_facts=bridge.student_facts if facts else None)
    with germany_student() as (client, who, params), level("master"), \
            patch("app.database.new_session", lambda: who.factory()):
        vault((client, who, params))
        data(choose_with(client, params, destination="DE", places=places, intake=WINTER))
        assert run_os(svc_) == [("planned", None)]
        yield Flow(svc_, client, who, params)


def ledger(f) -> dict:
    """The decision versions and the two sides' view of the plan."""
    return {"versions": f.versions(), "app": chosen(f.client, f.params)["plan"]["decision_version"],
            "os": bridge.plan_view(f.ref)["decision_version"]}


def places_of_plan(f) -> list[str]:
    contract, _ = f.svc.plans._contract(f.plan_id())
    return [p.programme_ref for p in sorted(contract.programmes, key=lambda p: p.rank)]


@pytest.mark.connect_row("6.5", "6.6")
def test_6_5_6_6_a_vault_drop_ends_in_a_request_and_version_2_both_sides(world):  # noqa: F811
    """Rows 6.5 and 6.6: marks drop in the Vault -> a pending removal -> accept -> the Counsellor writes version 2 ->
    the OS revises; the proposal is accepted and both sides read version 2 with two places. Then a stale one."""
    with patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True):
        for ref, band in ((OVGU, 5.0), (BTU_AI, 7.5), (BTU_CYBER, 5.0)):
            ielts_needs(world, ref, band)
        with flow(world, THREE, facts=True) as f:
            before = chat_rows(f.who)
            ws = f.ref
            assert ledger(f) == {"versions": [1], "app": 1, "os": 1}
            assert places_of_plan(f) == [OVGU, BTU_AI, BTU_CYBER]

            with f.who.factory() as db:
                # the first test score meets every bar: the rules propose nothing
                write(db, ws, "student_record", "test_attempt", {"test_type": "IELTS", "overall_score": "8.0"})
                assert bridge.deliver_pending(db, ws)["delivered"] >= 1
                assert [d.status for d in run_rules(SimpleNamespace(engine=f.svc.engine, replanner=f.r),
                                                    f.plan_id())] == ["applied"]
                assert f.r.proposals.pending_for(ws) == []
                # 1. the score is corrected downwards: one place no longer fits
                write(db, ws, "student_record", "test_attempt", {"test_type": "IELTS", "overall_score": "6.0"})
                assert bridge.deliver_pending(db, ws)["delivered"] >= 1
            (decision,) = run_rules(SimpleNamespace(engine=f.svc.engine, replanner=f.r), f.plan_id())
            assert decision.status == "pending", f.proposal(decision.proposal_id).refused
            proposal = f.proposal(decision.proposal_id)
            assert [(o["op"], o["programme_ref"]) for o in proposal.ops] == [("cancel_programme", BTU_AI)]
            assert chosen(f.client, f.params)["plan"]["proposals_waiting"] == 1
            assert places_of_plan(f) == [OVGU, BTU_AI, BTU_CYBER]  # nothing is removed by itself (R-07)

            # 2. accept: the OS changes nothing itself; it asks the Counsellor
            f.r.accept(ws, proposal.id)
            assert f.proposal(proposal.id).status == "requested"
            assert places_of_plan(f) == [OVGU, BTU_AI, BTU_CYBER] and f.versions() == [1]
            assert chosen(f.client, f.params)["plan"]["proposals_waiting"] == 0

            # 3. the hook delivers: version 2 with two places
            bridge.deliver_choice_request_now(choice_requests.key_of(proposal.id))
            assert f.versions() == [1, 2]
            assert [p["programme_ref"] for p in f.decision(2).places] == [OVGU, BTU_CYBER]

            # 4. the OS applies it as a revision; the proposal is accepted
            assert run_os(f.svc) == [("revised", None)]
            assert f.proposal(proposal.id).status == "accepted"
            assert places_of_plan(f) == [OVGU, BTU_CYBER]
            assert ledger(f) == {"versions": [1, 2], "app": 2, "os": 2}

            # 5. stale: a proposal on version 2, then the student changes the places (version 3), then accept
            stale = f.propose(OVGU)
            data(choose_with(f.client, f.params, destination="DE", places=[{"ref": OVGU, "rank": 1}], intake=WINTER))
            assert f.versions() == [1, 2, 3]
            f.r.accept(ws, stale)  # the plan has not applied version 3 yet, so the OS still accepts the tap
            assert f.proposal(stale).status == "requested"
            assert f.sweep()["stale"] == 1
            p = f.proposal(stale)
            assert p.status == "expired" and p.request_outcome == "stale"
            assert f.versions() == [1, 2, 3]  # no version 4
            assert run_os(f.svc) == [("revised", None)]  # the student's own change still applies
            assert places_of_plan(f) == [OVGU]
            assert ledger(f) == {"versions": [1, 2, 3], "app": 3, "os": 3}
            no_chat(f.who, before)
            assert_consistent(f.who.factory)  # the end-of-test check (R-04, R-05)


def at_chosen(f) -> None:
    """The student's Counsellor journey reaches the route decision (the stage sync of a full session does this)."""
    from app.journey import JourneyService

    with f.who.factory() as db:
        service = JourneyService(db)
        journey = service.ensure_counselor(f.ref)
        for stage in ("FOUNDATION", "DIRECTION", "MIRROR", "PROPOSED", "CHOSEN"):
            journey = service.set_counselor_stage(f.ref, journey.id, stage, validated_choice=stage == "CHOSEN")
        db.commit()


def journey_stage(f) -> str:
    with f.who.factory() as db:
        return db.scalar(select(StudentJourney.current_stage).where(StudentJourney.workspace_id == f.ref))


@pytest.mark.connect_row("6.12")
def test_6_12_all_rejected_pauses_the_plan_and_a_new_choice_resumes_it(world):  # noqa: F811
    with patch.object(config, "PAI_OS_SERVICE_TOKEN", SERVICE_TOKEN), \
            patch.object(config, "CONNECT_CONSENT_DRAFT", True, create=True), \
            flow(world, [{"ref": OVGU, "rank": 1}, {"ref": BTU_AI, "rank": 2}]) as f:
        before = chat_rows(f.who)
        assert chosen(f.client, f.params)["plan"]["state"] != "paused"
        at_chosen(f)
        assert journey_stage(f) == "CHOSEN"
        # 1. an admission is rejected on every place: the Counsellor hears `all_rejected`
        with f.svc.engine.begin() as conn:
            from app.os.replan import events

            eid = events.record(conn, "pai", f.plan_id(), "admission_rejected", {"programme_ref": BTU_AI}, "t6-flow-1")
        case = f.svc.escalations.escalate(f.plan_id(), [eid], "Supervisor: nothing left to apply to")
        assert case
        with f.who.factory() as db:
            assert bridge.sweep_once(db)["sent"] == 1
        with f.who.factory() as db:
            row = db.scalar(select(StudentJourney).where(StudentJourney.workspace_id == f.ref))
            assert row.decisions[-1]["reason_type"] == "all_rejected"
        # 2. the journey is back to choosing, the plan is paused with the reason, the roadmap says so
        assert journey_stage(f) == "PROPOSED"
        view = bridge.plan_view(f.ref)
        assert (view["state"], view["state_reason"]) == ("paused", "all_rejected")
        plan = chosen(f.client, f.params)["plan"]
        assert plan["state"] == "paused" and plan["state_reason"] == "all_rejected"
        assert plan["reason_text"] and plan["reason_action"]
        # 3. a consent copy of the same choice does not resume the plan
        with f.who.factory() as db:
            RouteDecisionService(db).update_consent(f.ref, authorized_at=datetime(2026, 11, 20, tzinfo=timezone.utc))
            db.commit()
            bridge.deliver_pending(db, f.ref)
        assert f.versions() == [1, 2]
        assert run_os(f.svc) == [("revised", None)]
        assert bridge.plan_view(f.ref)["state"] == "paused"
        assert chosen(f.client, f.params)["plan"]["state_reason"] == "all_rejected"
        # 4. a new choice resumes it and revises
        data(choose_with(f.client, f.params, destination="DE", places=[{"ref": OVGU, "rank": 1}], intake=WINTER))
        assert run_os(f.svc) == [("revised", None)]
        assert bridge.plan_view(f.ref)["state"] != "paused"
        assert journey_stage(f) == "CHOSEN"
        assert places_of_plan(f) == [OVGU]
        assert ledger(f)["app"] == ledger(f)["os"] == f.versions()[-1]
        no_chat(f.who, before)
        assert_consistent(f.who.factory)  # the end-of-test check (R-04, R-05)


def builder(world_, who):
    ports.configure(world_, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice,
                    choice_sink_enabled=bridge.choice_enabled)
    os_api = os_client(world_)
    agree(os_api, who.workspace_id)
    return os_api, {"X-Test-Student": who.workspace_id}


@pytest.mark.connect_row("6.13")
def test_6_13_the_builder_with_the_counsellor_on_writes_the_next_version(world):  # noqa: F811
    with flow(world, [{"ref": OVGU, "rank": 1}]) as f:
        before = chat_rows(f.who)
        os_api, h = builder(world, f.who)
        body = {**START, "choices": [{"programme_ref": OVGU, "rank": 1}, {"programme_ref": BTU_AI, "rank": 2}]}
        r = os_api.post("/v1/os/plans/self", headers=h, json=body)
        assert r.status_code == 202, r.text
        assert r.json()["state"] == "preparing" and r.json()["decision_version"] == 2
        assert f.versions() == [1, 2]
        assert count(world, "self_serve") == 0  # the builder made no plan of its own
        assert run_os(world) == [("revised", None)]
        assert count(world, "self_serve") == 0 and count(world, "counsellor") == 1
        assert places_of_plan(f) == [OVGU, BTU_AI]  # the Counsellor's plan, made from the intake
        assert ledger(f) == {"versions": [1, 2], "app": 2, "os": 2}
        no_chat(f.who, before)
        assert_consistent(f.who.factory)  # the end-of-test check (R-04, R-05)


@pytest.mark.connect_row("6.16")
def test_6_16_a_self_serve_plan_is_adopted_when_the_student_agrees(world):  # noqa: F811
    with germany_student() as (client, who, params), level("master"), \
            patch.object(config, "CONNECT_MY_PLAN", True, create=True):
        vault((client, who, params))
        plan_id = own_plan(world, who.workspace_id)
        before_tasks = tasks(world, plan_id)
        before = chat_rows(who)
        early = data(client.get("/v1/roadmap/adoption", params=params, headers=TOKEN))
        assert early["state"] == "choose_field_first"  # no chosen field yet: the screen shows a sentence, no button
        refused = client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id})
        assert refused.status_code == 409
        # the student chooses a field (a first choice in PAI); the plan of their own stays open
        data(choose_with(client, params, destination="DE", places=[{"ref": OVGU, "rank": 1}], intake=WINTER))
        assert run_os(world) == [("refused", "self_serve_plan_open")]
        ports.configure(world, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice,
                        choice_sink_enabled=bridge.choice_enabled)
        offer = data(client.get("/v1/roadmap/adoption", params=params, headers=TOKEN))
        assert offer["offer"] is True and offer["plan"]["plan_id"] == plan_id
        posted = data(client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": plan_id}))
        assert posted == {"state": "linking", "decision_version": 2}  # the version is written
        with who.factory() as db:
            assert db.scalar(select(func.max(RouteDecision.decision_version)).where(
                RouteDecision.workspace_id == who.workspace_id)) == 2
        assert run_os(world) == [("revised", None)]
        assert sources(world) == {"counsellor": 1}  # the same plan id, now the Counsellor's
        with world.engine.connect() as conn:
            assert conn.execute(select(models.plans.c.id)).scalars().all() == [plan_id]
        assert tasks(world, plan_id) == before_tasks  # the same tasks
        assert chosen(client, params)["plan"]["decision_version"] == 2
        assert bridge.plan_view(who.workspace_id)["decision_version"] == 2
        no_chat(who, before)
        assert_consistent(who.factory)  # the end-of-test check (R-04, R-05)


@pytest.mark.connect_row("6.17")
def test_6_17_with_the_module_off_the_plans_stay_standalone_and_accept_edits_directly(world):  # noqa: F811
    with germany_student() as (client, who, params), level("master"):
        before = chat_rows(who)
        with world.engine.begin() as conn:  # the Counsellor module is switched off
            conn.execute(update(models.modules).where(models.modules.c.module == "counsellor").values(enabled=False))
        os_api, h = builder(world, who)
        body = {**START, "choices": [{"programme_ref": OVGU, "rank": 1}, {"programme_ref": BTU_AI, "rank": 2}]}
        r = os_api.post("/v1/os/plans/self", headers=h, json=body)
        assert r.status_code == 201, r.text  # a standalone plan, as before
        assert count(world, "self_serve") == 1 and count(world, "counsellor") == 0
        with who.factory() as db:  # nothing was asked of the Counsellor
            assert db.scalar(select(func.count()).select_from(RouteDecision).where(
                RouteDecision.workspace_id == who.workspace_id)) == 0
        f = Flow(world, client, who, params)
        pid = f.propose(BTU_AI)
        f.r.accept(f.ref, pid)  # direct edit: no request, no outbox row, no Counsellor
        p = f.proposal(pid)
        assert p.status == "accepted" and p.revision is not None
        assert f.requests() == [] and f.versions() == []
        assert set(f.r.overrides.cancelled(f.plan_id())) == {BTU_AI}  # the plan itself dropped the place (an override)
        no_chat(who, before)
