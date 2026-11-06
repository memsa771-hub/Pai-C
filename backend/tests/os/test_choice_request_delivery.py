"""P1-T6 Task 3 (R-07, row 6.6): an accepted choice request goes from the OS outbox to the Counsellor's decision
service, comes back as version n+1, and the OS intake revises the plan: the proposal ends `accepted`, once, and both
sides show the same version. Counsellor side: the real HTTP API on a student session; OS side: real services on
Postgres. Fictional students; the mailer is stubbed."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app import pai_os_bridge as bridge
from app.models import OsOutbox, RouteDecision
from app.os import models, ports
from app.os.adapters.counsellor.store import IntakeStore
from app.os.outbox import Outbox
from app.os.ports import choice_requests
from app.os.replan import events
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import text

from app.os.knowledge.programmes import ProgrammeStore
from app.os.replan.apply import Replanner, ProposalStale
from app.os.replan.config import load_replan_configs
from app.os.replan.ops import CancelProgramme
from app.os.replan.store import ProposalStore
from tests.os.test_connect_t5_flow import (WINTER, chosen, germany_student, level, run_os, vault,  # noqa: F401
                                           world)
from tests.os.test_counsellor_intake_v2 import svc  # noqa: F401 - the fixture is used by name
from tests.test_roadmap_choice_api import choose_with
from tests.test_roadmap_api import TOKEN, data

pytestmark = pytest.mark.req("R-07")

PR, P, O = models.proposals, models.plans, models.outbox
PLACES = [{"ref": "ovgu-eeit", "rank": 1}, {"ref": "btu-artificial-intelligence", "rank": 2}]
WHY = "The programme did not admit you: its remaining steps are removed."


class Flow:
    def __init__(self, svc, client, who, params):
        self.svc, self.client, self.who, self.params = svc, client, who, params
        self.r = Replanner(svc.engine, svc.plans, load_replan_configs(), Outbox(svc.engine, "pai"))
        self.store = ProposalStore(svc.engine, "pai")
        self.n = 0

    @property
    def ref(self) -> str:
        return self.who.workspace_id

    def plan_id(self) -> int:
        with self.svc.engine.connect() as conn:
            return conn.execute(select(P.c.id).where(P.c.student_ref == self.ref)).scalar_one()

    def propose(self, programme="btu-artificial-intelligence") -> int:
        self.n += 1
        with self.svc.engine.begin() as conn:
            eid = events.record(conn, "pai", self.plan_id(), "admission_rejected", {"programme_ref": programme},
                                f"k{self.n}")
        d = self.r.decide(self.plan_id(), [eid], "rules", [CancelProgramme(programme_ref=programme, reason=WHY)])
        assert d.status == "pending"
        return d.proposal_id

    def proposal(self, pid):
        return self.store.get(pid)

    def versions(self) -> list[int]:
        with self.who.factory() as db:
            return sorted(db.scalars(select(RouteDecision.decision_version).where(
                RouteDecision.workspace_id == self.ref)))

    def decision(self, version):
        with self.who.factory() as db:
            return db.scalar(select(RouteDecision).where(RouteDecision.workspace_id == self.ref,
                                                         RouteDecision.decision_version == version))

    def outbox_keys(self) -> list[str]:
        with self.who.factory() as db:
            return sorted(db.scalars(select(OsOutbox.key).where(OsOutbox.workspace_id == self.ref)))

    def requests(self):
        with self.svc.engine.connect() as conn:
            return conn.execute(select(O).where(O.c.template == "choice_request").order_by(O.c.id)).all()

    def sweep(self) -> dict:
        with self.who.factory() as db:
            return bridge.deliver_choice_requests(db)


@contextmanager
def flow(world):  # noqa: F811
    svc = world
    ports.configure(svc, choice_enabled=bridge.choice_enabled, on_choice_request=None)
    with germany_student() as (client, who, params), level("master"), \
            patch("app.database.new_session", lambda: who.factory()):
        vault((client, who, params))
        data(choose_with(client, params, destination="DE", places=PLACES, intake=WINTER))
        assert run_os(svc) == [("planned", None)]
        yield Flow(svc, client, who, params)


def test_bridge_delivers_and_proposal_accepted_after_intake(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        p = f.proposal(pid)
        assert p.status == "requested" and p.base_decision_version == 1
        key = choice_requests.key_of(pid)
        bridge.deliver_choice_request_now(key)
        assert f.versions() == [1, 2]
        p = f.proposal(pid)
        assert p.status == "requested" and p.requested_version == 2 and p.request_outcome == "written"
        assert f.decision(2).request_key == key and f.requests()[0].status == "sent"
        assert f.outbox_keys() == [f"decision:{f.ref}:1", f"decision:{f.ref}:2"]
        assert run_os(f.svc) == [("revised", None)]
        p = f.proposal(pid)
        assert p.status == "accepted" and p.revision is not None
        contract, _ = f.svc.plans._contract(f.plan_id())
        assert [x.programme_ref for x in contract.programmes] == [x["programme_ref"] for x in f.decision(2).places]
        assert [x.programme_ref for x in contract.programmes] == ["ovgu-eeit"]
        assert chosen(f.client, f.params)["plan"]["decision_version"] == 2  # row 6.6: the same version both sides


def test_stale_answer_expires_proposal(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        data(choose_with(f.client, f.params, destination="DE", places=PLACES[:1], intake=WINTER))  # a real change
        assert f.versions() == [1, 2]
        assert f.sweep()["stale"] == 1
        p = f.proposal(pid)
        assert p.status == "expired" and p.request_outcome == "stale" and p.requested_version is None
        assert f.versions() == [1, 2] and f.requests()[0].status == "sent"
        assert f.sweep() == {"written": 0, "duplicate": 0, "stale": 0, "refused": 0, "failed": 0, "skipped": 0}


def test_mark_after_intake_settles_at_once(world):
    """D-x3 ordering: the plan applies n+1 before the mark arrives."""
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        with f.who.factory() as db:  # the app side commits and the OS takes the version; the mark has not arrived
            from app.pai_c.roadmap.decisions import RouteDecisionService
            req = choice_requests.pending()[0]
            assert RouteDecisionService(db).apply_choice_request(
                f.ref, req.model_dump(mode="json", by_alias=True)) == ("written", 2)
            db.commit()
            bridge.deliver_pending(db, f.ref)
        assert run_os(f.svc) == [("revised", None)]
        assert f.proposal(pid).status == "requested"  # no requested_version yet: not settled by the intake
        choice_requests.mark_delivery(choice_requests.key_of(pid), "written", 2)
        p = f.proposal(pid)
        assert p.status == "accepted" and p.requested_version == 2


def test_crash_after_app_commit_before_mark(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        with patch.object(choice_requests, "mark_delivery", side_effect=RuntimeError("killed")):
            assert f.sweep()["failed"] == 1
        assert f.versions() == [1, 2] and f.proposal(pid).requested_version is None
        assert f.requests()[0].status == "pending"
        assert f.sweep()["duplicate"] == 1  # the re-sweep finds its version, never n+2
        assert f.versions() == [1, 2]
        assert run_os(f.svc) == [("revised", None)]
        assert f.proposal(pid).status == "accepted" and f.proposal(pid).request_outcome == "duplicate"


def test_nothing_pending_after_mark_so_no_second_version_and_intake_settles(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        assert f.sweep()["written"] == 1
        assert f.sweep()["written"] == 0 and f.versions() == [1, 2]  # nothing pending: no second version
        assert f.proposal(pid).status == "requested"
        assert run_os(f.svc) == [("revised", None)]
        assert f.proposal(pid).status == "accepted"
        assert run_os(f.svc) == []
        assert f.versions() == [1, 2]


def test_failed_delivery_leaves_the_row_pending(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        with patch("app.pai_c.roadmap.decisions.RouteDecisionService.apply_choice_request",
                   side_effect=RuntimeError("db down")):
            assert f.sweep()["failed"] == 1
        assert f.versions() == [1] and f.requests()[0].status == "pending"
        assert f.sweep()["written"] == 1


def test_withdrawn_plan_expires_requested_proposal(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        assert f.sweep()["written"] == 1
        data(f.client.post("/v1/roadmap/withdraw", params=f.params, headers=TOKEN))
        run_os(f.svc)
        p = f.proposal(pid)
        assert p.status == "expired" and p.request_outcome == "written"  # the outcome stays as delivered


def test_a_second_request_for_one_plan_comes_back_stale(world):
    """Two requests for one plan (from before the accept guard) are delivered oldest first; the second is stale."""
    with flow(world) as f:
        first, second = f.propose("btu-artificial-intelligence"), f.propose("ovgu-eeit")
        with patch.object(Replanner, "_request_open", return_value=False):
            f.r.accept(f.ref, first)
            f.r.accept(f.ref, second)
        assert len(f.requests()) == 2
        assert f.sweep() == {"written": 1, "duplicate": 0, "stale": 1, "refused": 0, "failed": 0, "skipped": 0}
        assert f.versions() == [1, 2]
        assert f.proposal(first).request_outcome == "written"
        assert f.proposal(second).status == "expired" and f.proposal(second).request_outcome == "stale"


def test_accept_guard_refuses_while_a_request_is_open(world):
    """Carried from the Task 2 review: a second choice-changing accept on a plan with a `requested` proposal is 409
    `request_open`, and no second outbox row is written."""
    with flow(world) as f:
        first, second = f.propose("btu-artificial-intelligence"), f.propose("ovgu-eeit")
        f.r.accept(f.ref, first)
        with pytest.raises(ProposalStale, match="request_open"):
            f.r.accept(f.ref, second)
        assert len(f.requests()) == 1 and f.proposal(second).status == "pending"


def test_sweep_skips_choice_requests_when_handoff_off(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        with patch.object(bridge.config, "CONNECT_HANDOFF", False, create=True):
            with f.who.factory() as db:
                bridge.sweep_once(db)
            bridge.deliver_choice_request_now(choice_requests.key_of(pid))
        assert f.versions() == [1] and f.requests()[0].status == "pending"
        assert f.proposal(pid).status == "requested"


def test_crash_between_revision_and_settle_then_rerun(world):
    """Kill point: the intake applied n+1 but died before settling the request. DBOS runs `process` again: the
    revision is not repeated and the proposal is settled."""
    from app.os.adapters.counsellor import intake as intake_mod

    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        assert f.sweep()["written"] == 1
        with patch.object(intake_mod, "_settle_requests", side_effect=RuntimeError("killed")):
            with pytest.raises(RuntimeError):
                run_os(f.svc)
        assert f.proposal(pid).status == "requested"
        with f.svc.engine.connect() as conn:
            causes = conn.execute(select(models.plan_revisions.c.cause)).scalars().all()
        store = IntakeStore(f.svc.engine, "pai")
        again = intake_mod.process(f.svc, store.get(_pending(store, f)[0].decision_id))
        assert again.status == "revised" and f.proposal(pid).status == "accepted"
        with f.svc.engine.connect() as conn:
            assert conn.execute(select(models.plan_revisions.c.cause)).scalars().all() == causes


def _pending(store, f):
    I = models.counsellor_intake
    with f.svc.engine.connect() as conn:
        return conn.execute(select(I.c.decision_id).where(I.c.student_ref == f.ref, I.c.decision_version == 2)).all()


def retire(f, ref, status="excluded"):
    store = ProgrammeStore(f.svc.engine, "pai")
    store.upsert(replace(store.get(ref), status=status))


def test_refused_version_expires_the_request_and_a_consent_copy_cannot_settle_it(world):
    """A programme retired between accept and intake: the OS refuses n+1, the request expires (outcome as
    delivered), a new accept is no longer blocked by request_open, and a later consent copy settles nothing."""
    from app.pai_c.roadmap.decisions import RouteDecisionService

    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        assert f.sweep()["written"] == 1
        retire(f, "ovgu-eeit")  # the one place v2 keeps
        assert run_os(f.svc) == [("refused", "unknown_programme")]
        p = f.proposal(pid)
        assert p.status == "expired" and p.request_outcome == "written" and p.requested_version == 2
        assert f.r._request_open(f.plan_id()) is False
        retire(f, "ovgu-eeit", "active")
        with f.who.factory() as db:
            RouteDecisionService(db).update_consent(f.ref, authorized_at=datetime(2026, 11, 20, tzinfo=timezone.utc))
            db.commit()
            bridge.deliver_pending(db, f.ref)
        assert run_os(f.svc) == [("revised", None)]  # the consent copy of v2 applies
        assert f.proposal(pid).status == "expired"  # and does not settle the refused request


def test_non_uuid_student_ref_is_refused_and_the_row_sent(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        with f.svc.engine.begin() as conn:
            conn.execute(text("UPDATE os.os_outbox SET payload = jsonb_set(payload, '{student_ref}', '\"not-a-uuid\"') "
                              "WHERE template = 'choice_request'"))
        assert f.sweep()["refused"] == 1
        p = f.proposal(pid)
        assert p.status == "expired" and p.request_outcome == "refused"
        assert f.requests()[0].status == "sent" and f.versions() == [1]


def test_pending_row_of_a_closed_proposal_is_sent_not_applied(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        assert f.store.expire_requested(pid, None)  # the proposal moved on while its row still waits
        assert f.sweep()["skipped"] == 1
        assert f.versions() == [1] and f.requests()[0].status == "sent"
        assert f.proposal(pid).status == "expired" and f.proposal(pid).request_outcome is None


def test_mark_delivery_is_one_transaction(world):
    with flow(world) as f:
        pid = f.propose()
        f.r.accept(f.ref, pid)
        # the outbox update fails AFTER the proposal update: both roll back
        calls = []

        def boom(*a, **k):
            calls.append(1)
            raise RuntimeError("down")

        with patch.object(choice_requests, "update", boom):
            with pytest.raises(RuntimeError):
                choice_requests.mark_delivery(choice_requests.key_of(pid), "stale")
        assert calls
        assert f.proposal(pid).status == "requested" and f.requests()[0].status == "pending"
        choice_requests.mark_delivery(choice_requests.key_of(pid), "stale")
        assert f.proposal(pid).status == "expired" and f.requests()[0].status == "sent"
