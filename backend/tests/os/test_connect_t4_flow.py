"""P1-T4 Task 6 (R-13, R-15, R-16): the whole student-facts flow against a real PAI OS. A Vault write on a student
session (SQLite) bumps the Vault version and queues the outbox row; the bridge delivers it; PAI OS records the event on
the student's plan; the replan sweep queues the replan; the rules read the Vault through the Counsellor's adapter and end
in a pending big proposal. The OS side is the real services on Postgres with the fake Pakistan bachelor route and fake
merit thresholds. Fictional student and marks."""

import types as pytypes
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import func, select

from app import pai_os_bridge as bridge
from app.config import config
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import MemoryCandidate, OsOutbox
from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.os.api import make_services
from app.os.contracts.route_contract import RouteContract
from app.os.documents.types import DocumentType, FieldSpec
from app.os.eligibility import facts as eligibility_facts
from app.os.eligibility.facts import current_types
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.outbox import Outbox
from app.os.playbooks import load_playbook_dir
from app.os.replan.apply import Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.events import pending
from app.os.replan.rules import rules_for
from app.os.replan.run import run_replan_job
from app.pai_c.connect import student_facts as host_facts
from scripts.counselor_eval_support import StudentSession

pytestmark = [pytest.mark.req("R-13"), pytest.mark.req("R-15"), pytest.mark.req("R-16")]

FAKE = Path(__file__).parent / "playbooks"
TENANT, NOW = "pai", datetime(2026, 11, 5, tzinfo=timezone.utc)
# the fake local entry test is not a shipped document type: this test adds one so the mapping covers it
ENTRY_TYPE = DocumentType(key="entry_test", version=1, label="Entry test",
                          fields=[FieldSpec(name="score", type="number", hint="Score", fact="test.entry_test.score")])


class Queue:
    """Stands in for the DBOS client: records what the replan sweep enqueues."""

    def __init__(self):
        self.jobs = []

    def enqueue(self, options, plan_id, event_id):
        self.jobs.append((plan_id, event_id))


@pytest.fixture
def os_world(engine, clean, os_db):
    settings = load_settings_for(os_db)
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), today=lambda: date(2026, 11, 5))
    store, kb = ProgrammeStore(engine, TENANT), SqlKnowledge(engine, TENANT)
    for ref, closing in (("p-easy", 50), ("p-hard", 80)):  # fake merit thresholds
        store.upsert(Programme(ref=ref, route_key="pakistan_bs", university="Uni X", name=ref, aliases=(),
                               start_urls=("https://uni.example/x",), official_domains=("uni.example",)))
        for field, value in (("merit_closing", {"aggregate": closing}), ("entry_test_required", {"any_of": []})):
            kb.upsert("programme", ref, field, Fact(value, "q", "https://uni.example/x", NOW, 2027, "confirmed"),
                      "manual")
    manifest.set_enabled(engine, TENANT, True)
    replanner = Replanner(engine, svc.plans, load_replan_configs(), Outbox(engine, TENANT), clock=lambda: NOW)
    yield pytypes.SimpleNamespace(svc=svc, engine=engine, replanner=replanner)
    ports.configure(None)


def load_settings_for(os_db):
    from app.os.settings import load_settings

    return load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true"})


def write(db, ws, candidate_type, key, value, **kw):
    candidate = MemoryCandidateService(db).propose(
        ws, candidate_type, key=key, proposed_value=value, confidence=0.9, source_type="user_explicit",
        allow_user_explicit=True, input_channel="profile", evidence={"quote": "q", "capture": "details"}, **kw)
    assert MemoryReconciler(db).reconcile(candidate).accepted
    db.commit()
    return candidate


def vault_rows(db, ws) -> list:
    db.expire_all()
    return list(db.scalars(select(OsOutbox).where(OsOutbox.workspace_id == ws, OsOutbox.kind == "vault_event")
                           .order_by(OsOutbox.created_at, OsOutbox.key)))


def run_rules(world, plan_id):
    """What the os.replan workflow does for each pending event, called directly: the rules, then the decision."""
    out = []
    for e in pending(world.engine, TENANT, plan_id):
        got = rules_for(e, world.replanner.state(plan_id, with_below=True), world.replanner.config(plan_id))
        out.append(world.replanner.decide(plan_id, [e.id], "rules", got))
    return out


def test_a_vault_write_that_drops_marks_ends_in_a_pending_big_proposal(os_world):
    with StudentSession() as student, student.factory() as db, patch.object(config, "CONNECT_STUDENT_FACTS", True,
                                                                           create=True):
        ws = student.workspace_id
        ports.configure(os_world.svc, student_facts=lambda ref: host_facts.build(db, ref))
        eligibility_facts.configure_types(current_types() | {"entry_test": ENTRY_TYPE})
        contract = RouteContract.model_validate({
            "contract_version": "1", "source": "self_serve", "external_ref": f"self:{ws}", "student_ref": ws,
            "origin_country": "PK", "destination_country": "PK", "level": "bachelor",
            "target_intake": {"term": "winter", "year": 2027},
            "programmes": [{"programme_ref": "p-easy", "rank": 1}, {"programme_ref": "p-hard", "rank": 2}]})
        plan_id = os_world.svc.plans.start_plan(contract).plan_id

        # 1. the first Vault facts: both programmes fit, so the replan has nothing to change
        first = write(db, ws, "student_record", "education",
                      {"qualification_name": "FSc", "institution_name": "A College", "academic_status": "completed",
                       "result": {"marks_obtained": 1000, "marks_total": 1100}})
        write(db, ws, "student_record", "test_attempt", {"test_type": "entry_test", "overall_score": "80"})
        assert [r.status for r in vault_rows(db, ws)] == ["pending", "pending"]
        assert bridge.deliver_pending(db, ws) == {"delivered": 2, "failed": 0, "not_sent": 0}
        assert [d.status for d in run_rules(os_world, plan_id)] == ["applied", "applied"]
        assert os_world.replanner.proposals.pending_for(ws) == []

        # 2. the marks are corrected downwards: the hook bumps the version and queues the row...
        before = len(vault_rows(db, ws))
        write(db, ws, "student_record", "education", {"result": {"marks_obtained": 800}},
              entities={"record_id": db.get(MemoryCandidate, first.id).result_id})
        (row,) = vault_rows(db, ws)[before:]
        assert row.status == "pending" and row.payload["vault_version"] == 3
        # 3. ...the bridge delivers it and PAI OS records the event on the plan...
        assert bridge.deliver_pending(db, ws)["delivered"] == 1
        with os_world.engine.connect() as conn:
            fact_events = conn.execute(select(models.events.c.plan_id, models.events.c.payload).where(
                models.events.c.type == "student_fact_changed", models.events.c.plan_id == plan_id)
                .order_by(models.events.c.id)).all()
        assert [p["vault_version"] for _, p in fact_events] == [1, 2, 3]
        assert "education.intermediate.marks_obtained" in fact_events[-1].payload["keys"]
        # 4. ...the replan sweep queues one replan for it...
        queue = Queue()
        assert run_replan_job(os_world.replanner, queue, NOW) == 1 and queue.jobs[0][0] == plan_id
        # 5. ...and the rules end in a pending big proposal; nothing is removed by itself
        (decision,) = run_rules(os_world, plan_id)
        assert decision.status == "pending"
        proposal = os_world.replanner.proposals.get(decision.proposal_id)
        assert proposal.big and [(o["op"], o["programme_ref"]) for o in proposal.ops] == [("cancel_programme", "p-hard")]
        assert [p.programme_ref for p in os_world.svc.plans._contract(plan_id)[0].programmes] == ["p-easy", "p-hard"]
        # a repeated delivery and a repeated sweep add nothing
        assert bridge.deliver_pending(db, ws) == {"delivered": 0, "failed": 0, "not_sent": 0}
        assert run_rules(os_world, plan_id) == []
        with os_world.engine.connect() as conn:
            assert conn.execute(select(func.count()).select_from(models.proposals)).scalar() == 3
