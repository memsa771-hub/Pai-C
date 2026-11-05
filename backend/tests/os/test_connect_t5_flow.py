"""P1-T5 Task 7 (R-04, R-44, R-45): the whole plan-view flow against a real PAI OS. The Counsellor side is the real HTTP
API on a student session; the OS side is the real services behind the ports on Postgres. Each step delivers (as the
request does), runs the OS intake and reads the roadmap. Germany route (the real playbook), the fake Pakistan
intermediate route, and a route PAI OS cannot run. Fictional students; the mailer is stubbed. No chat row is made."""

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from sqlalchemy import func, select, update

from app import pai_os_bridge as bridge
from app.config import config
from app.memory.vault import VaultService
from app.models import Base, NotificationRecord
from app.os import models, ports
from app.pai_c.connect import places
from app.os.adapters.counsellor.intake import process
from app.os.adapters.counsellor.store import IntakeStore
from app.os.kernel.kernel import Outcome
from app.security import rate_limit
from app.services import auth_emails
from tests.os.test_counsellor_intake_v2 import svc  # noqa: F401 - the fixture is used by name
from tests.test_roadmap_api import TOKEN, data, roadmap_client
from tests.test_roadmap_choice_api import FIELD, choose_with, post, vault
from tests.test_roadmap_engine import fsc

pytestmark = [pytest.mark.req("R-04"), pytest.mark.req("R-44"), pytest.mark.req("R-45")]

WINTER = {"term": "winter", "year": 2027}
T = models.tasks


@pytest.fixture
def world(svc, engine, monkeypatch):  # noqa: F811
    """PAI OS on its ports with the Counsellor module on, the flags on, the mailer stubbed."""
    from sqlalchemy import insert

    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    ports.configure(svc)
    rate_limit.reset()
    monkeypatch.setattr(auth_emails, "send_email", lambda to, subject, html, text_body=None: True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    with patch.object(config, "CONNECT_HANDOFF", True, create=True), \
            patch.object(config, "CONNECT_ROADMAP_FROM_PLANVIEW", True, create=True), \
            patch("app.routers.roadmap.resolve_human", lambda db, ws, auth: SimpleNamespace()):
        try:
            yield svc
        finally:
            ports.configure(None)
            rate_limit.reset()


def run_os(svc) -> list[tuple[str, str | None]]:  # noqa: F811
    store = IntakeStore(svc.engine, "pai")
    done = []
    for intake in store.pending():
        result = process(svc, intake)
        store.finish(intake.id, result.status, result.reason, result.plan_id)
        done.append((result.status, result.reason))
    return done


def chosen(client, params) -> dict:
    return data(client.get("/v1/roadmap", params=params, headers=TOKEN))["chosen"]


def task(svc, plan_id, template):  # noqa: F811
    with svc.engine.connect() as conn:
        return conn.execute(select(T).where(T.c.plan_id == plan_id, T.c.template_key == template)).first()


def bell(who) -> list[tuple[str, str]]:
    with who.factory() as db:
        return [(n.dedupe_key.split(":")[2], n.title) for n in db.scalars(
            select(NotificationRecord).order_by(NotificationRecord.created_at, NotificationRecord.dedupe_key))]


def page_decision_id(svc, who):  # noqa: F811
    with svc.engine.connect() as conn:
        return conn.execute(select(models.counsellor_intake.c.decision_id).where(
            models.counsellor_intake.c.student_ref == who.workspace_id).order_by(
            models.counsellor_intake.c.decision_version)).scalars().first()


def no_chat(who, before: dict[str, int]) -> None:
    """Throughout (R-45): besides notifications, only the decision rows, their hand-off rows and the check-in job
    grew; no message, turn or event row."""
    after = row_counts(who)
    grew = {name for name in after if after[name] != before[name]}
    assert grew <= {"pai_os_outbox", "pai_route_decisions", "background_jobs"}, grew


def row_counts(who) -> dict[str, int]:
    """Row counts of every Counsellor table except notifications (messages, turns and events live in the others)."""
    from sqlalchemy import inspect

    have = set(inspect(who.engine).get_table_names())
    with who.factory() as db:
        return {t.name: db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables
                if t.name in have and t.name not in ("notifications",)}


def germany_student():
    """An FSc student (the roadmap engine cannot read a finished degree yet) whose next level is set to master."""
    from tests.test_roadmap_api import pre_eng

    return pre_eng()


@contextmanager
def level(name):
    with patch.object(places, "next_level", lambda *a: name), patch.object(places, "_eligible_levels",
                                                                           lambda *a: [name]):
        yield


def test_germany_route(world):
    svc = world  # noqa: F811
    with germany_student() as (client, who, params), level("master"):
        vault((client, who, params))
        before = row_counts(who)

        # 1. choose: the OS plans it, the roadmap shows the OS steps
        body = data(choose_with(client, params, destination="DE", places=[{"ref": "ovgu-eeit", "rank": 1}],
                                intake=WINTER))
        assert body["choice"]["os_supported"] is True
        assert chosen(client, params)["plan"] == {"state": "empty"}  # delivered, not yet applied: "being prepared"
        assert run_os(svc) == [("planned", None)]
        page = chosen(client, params)
        assert page["plan"]["state"] == "needs_student" and page["plan"]["decision_version"] == 1
        assert {s["kind"] for s in page["steps"]} == {"os"} and page["steps"]
        keys = {s["key"].split("@")[0]: s for s in page["steps"]}
        assert {"hec_attestation", "applications_submitted"} <= set(keys)
        assert keys["hec_attestation"]["tickable"] is True and keys["hec_attestation"]["status"] == "half"

        # 2. a student tick completes the OS task and the roadmap shows it done; the tick itself makes no notice
        with who.factory() as db:
            assert bridge.deliver_os_events(db)["sent"] >= 1
        assert [kind for kind, _ in bell(who)].count("plan_created") == 1
        noticed = len(bell(who))
        plan_id = IntakeStore(svc.engine, "pai").get(page_decision_id(svc, who)).plan_id
        hec = task(svc, plan_id, "hec_attestation")
        ticked = data(post(client, params, "steps", {"key": keys["hec_attestation"]["key"], "done": True}))
        assert {s["key"]: s["status"] for s in ticked["steps"]}[keys["hec_attestation"]["key"]] == "done"
        assert task(svc, plan_id, "hec_attestation").state == "done" and hec.state == "waiting_student"
        assert keys["hec_attestation"]["key"] in chosen(client, params)["steps_done"]
        again = post(client, params, "steps", {"key": keys["hec_attestation"]["key"], "done": True})
        assert again.status_code == 200 and keys["hec_attestation"]["key"] in data(again)["steps_done"]
        with who.factory() as db:
            bridge.deliver_os_events(db)
        assert "step_done" not in [kind for kind, _ in bell(who)[noticed:]]
        # ...while a step PAI itself finishes makes one "step done" notice
        work = task(svc, plan_id, "applications_submitted")
        with svc.engine.begin() as conn:  # the earlier steps are not walked here: the work step is made ready
            conn.execute(update(T).where(T.c.id == work.id).values(state="ready", attempt=1))
        assert svc.kernel.mark_running(work.id, 1)
        svc.kernel.apply_result(work.id, 1, Outcome("done"))
        with who.factory() as db:
            bridge.deliver_os_events(db)
            bridge.deliver_os_events(db)  # a repeat sweep adds nothing
        assert [kind for kind, _ in bell(who)[noticed:]].count("step_done") == 1

        # 3. a change of places: revised, the roadmap says what changed
        revision = chosen(client, params)["plan"]["revision"]
        data(choose_with(client, params, destination="DE", intake=WINTER,
                         places=[{"ref": "ovgu-eeit", "rank": 1}, {"ref": "btu-artificial-intelligence", "rank": 2}]))
        assert run_os(svc) == [("revised", None)]
        page = chosen(client, params)
        assert page["plan"]["state"] != "empty" and page["plan"]["decision_version"] == 2
        assert page["plan"]["revision"] > revision and page["plan"]["changes"]
        assert keys["hec_attestation"]["key"] in page["steps_done"]  # done work stays done

        # 4. withdraw: the plan is stopped
        data(post(client, params, "withdraw"))
        assert run_os(svc) == [("withdrawn", None)]
        assert bridge.plan_view(who.workspace_id)["state"] == "stopped"
        with who.factory() as db:
            bridge.deliver_os_events(db)
        assert "plan_stopped" in [kind for kind, _ in bell(who)]

        no_chat(who, before)


def test_fake_pakistan_intermediate_route_is_planned(world):
    svc = world  # noqa: F811
    from tests.test_roadmap_api import pre_eng

    with pre_eng() as (client, who, params), level("intermediate"):
        vault((client, who, params))
        before = row_counts(who)
        body = data(choose_with(client, params, destination="PK", places=[{"ref": "pk-i1", "rank": 1}], intake=WINTER))
        assert body["choice"]["level"] == "intermediate" and body["choice"]["os_supported"] is True
        assert run_os(svc) == [("planned", None)]  # D-u: the intermediate level is no longer refused
        page = chosen(client, params)
        assert page["plan"]["state"] != "empty" and page["plan"]["decision_version"] == 1
        assert [s["key"].split("@")[0] for s in page["steps"]][0] == "admission_form"
        assert page["steps"][0]["kind"] == "os" and page["steps"][0]["tickable"] is True
        assert bridge.plan_view(who.workspace_id)["route"]["level"] == "intermediate"
        with who.factory() as db:
            bridge.deliver_os_events(db)
        assert bell(who) and "chat" not in " ".join(t for _, t in bell(who)).lower()
        no_chat(who, before)


def test_a_route_the_os_cannot_run_keeps_the_labelled_checklist(world):
    svc = world  # noqa: F811
    from tests.test_roadmap_api import pre_eng

    with pre_eng() as (client, who, params):
        vault((client, who, params))
        with who.factory() as db:
            VaultService(db).apply_fact(who.workspace_id, "preferences.target_countries", ["United Kingdom"],
                                        "user_explicit")
            db.commit()
        before = row_counts(who)
        body = data(choose_with(client, params, destination="GB", places=[], intake={"term": "autumn", "year": 2027}))
        assert body["choice"]["os_supported"] is False  # the screen shows the "PAI can't run this plan yet" banner
        assert run_os(svc) == []
        page = chosen(client, params)
        assert page["choice"]["os_supported"] is False and "plan" not in page
        assert page["steps"] and all(s["kind"] != "os" for s in page["steps"])  # today's checklist, labelled steps
        assert bridge.plan_view(who.workspace_id)["state"] == "empty"
        with svc.engine.connect() as conn:
            assert conn.execute(select(func.count()).select_from(models.plans)).scalar() == 0
        with who.factory() as db:
            assert bridge.deliver_os_events(db) == {"sent": 0, "refused": 0, "waiting": 0, "stale": 0}
        assert bell(who) == []
        no_chat(who, before)
