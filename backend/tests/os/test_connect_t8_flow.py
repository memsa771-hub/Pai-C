"""P1-T8 Task 7 (R-17, R-18, R-19, R-20, R-21, R-22; rows 6.19, 6.21, 6.22, and the mechanism of 6.20): the whole
missing-and-wrong-data flow against a real PAI OS. The Counsellor side is the real HTTP API on a student session
(SQLite, a temp file store); the OS side is the real services on Postgres behind the real bridge adapters, the real
OS HTTP API, the real kernel, reminders, deadline engine and the os.replan workflow. The reader is the OS offline reader
on the committed sample documents (no model, no cost). The reconcile job is run inline. Germany master is the real
playbook (version 2); the Ireland and Pakistan routes are the fake ones (version 2) with the test calendar of
`needs_seed.yaml`. Fictional students; the mailer is stubbed; no chat message is created at any step."""

import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

from app import pai_os_bridge as bridge
from app.config import config
from app.files import storage
from app.memory.reconciler import MemoryReconciler
from app.models import FileRecord, MemoryCandidate, OsOutbox, ProfileIssue, User
from app.os import models, ports
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.documents.store import DocumentStore
from app.os.knowledge import SEED_DIR, Fact, SqlKnowledge, load_seed
from app.os.knowledge.programmes import PROGRAMME_SEED, Programme, ProgrammeStore, load_programme_seed
from app.os.outbox import Outbox
from app.os.playbooks import PLAYBOOK_DIR, Playbook, load_playbook_dir
from app.os.ports import choice_requests, fact_proposals
from app.os.replan import events
from app.os.replan.apply import Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.run import run_replan_job
from app.os.replan.store import SupportStore
from app.os.requests import store as request_store
from app.os.requests import texts
from app.os.settings import load_settings
from app.os.workers import deadline_engine, run_reminders
from tests.auth_fakes import firebase_tokens, link_owner
from tests.one_upload_support import post_file
from tests.os.test_api import TEST_TERMS
from tests.os.test_api_documents import FakeClient, simulate_read
from tests.os.test_choice_request_delivery import Flow
from tests.os.test_connect_t4_flow import write
from tests.os.test_connect_t5_flow import (  # noqa: F401 - fixtures and helpers
    WINTER,
    chosen,
    germany_student,
    level,
    row_counts,
    run_os,
    svc,
    vault,
)
from tests.os.test_connect_t6_flow import CHAT
from tests.os.test_counsellor_intake_v2 import svc as _intake_svc  # noqa: F401
from tests.os.test_unanswered_ladder import event_of, pending_proposals, running, sweep
from tests.test_roadmap_api import TOKEN, data, pre_eng
from tests.test_roadmap_choice_api import choose_with, post

pytestmark = [pytest.mark.req("R-17"), pytest.mark.req("R-18"), pytest.mark.req("R-19"), pytest.mark.req("R-20"),
              pytest.mark.req("R-21"), pytest.mark.req("R-22")]

TENANT = "pai"
HERE = Path(__file__).parent
FAKE_DIR, NEEDS_DIR = HERE / "playbooks", HERE / "playbooks" / "needs"
NEEDS_SEED = HERE / "fixtures" / "needs_seed.yaml"
SAMPLES = HERE / "fixtures" / "documents" / "samples"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
T, EV = models.tasks, models.events
MATRIC_MARKS, MATRIC_TOTAL = "education.matric.marks_obtained", "education.matric.marks_total"
INTER_MARKS, INTER_TOTAL = "education.intermediate.marks_obtained", "education.intermediate.marks_total"
GPA = "education.bachelor.gpa"
IELTS = "test.ielts.score"
SSC, HSSC, TRANSCRIPT_DOC = "ssc_certificate", "hssc_certificate", "transcript"
FACT_COLUMNS = {"id", "tenant_id", "student_ref", "plan_id", "task_id", "kind", "need_kind", "need_ref", "evidence",
                "status", "closed_cause", "created_at", "closed_at"}


def chat_rows(who) -> dict[str, int]:
    """Rows a chat message or turn would make. The Vault logs `vault.*` events and an upload logs a `workspace.file.*`
    event: neither is chat."""
    from app.models import Base

    events_table = Base.metadata.tables["events"]
    counts = row_counts(who)
    with who.factory() as db:
        counts["events"] = db.scalar(select(func.count()).select_from(events_table).where(
            ~events_table.c.type.like("vault.%"), ~events_table.c.type.like("workspace.file.%")))
    return {t: counts[t] for t in CHAT}


def sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()


class Clock:
    """The one test clock: `today` for the plan service and the deadline engine, `now` for reminders and the replan job."""

    def __init__(self, day=date(2027, 1, 20)):
        self.today = day

    @property
    def now(self) -> datetime:
        return datetime.combine(self.today, datetime.min.time(), timezone.utc) + timedelta(hours=8)

    def set(self, day: date) -> None:
        self.today = day


def germany_v3_with_a_gpa_need() -> Playbook:
    """The shipped Germany v2 plus one need, the CGPA at `stated`, on the two application steps. The shipped version 2 asks
    only for documents (it has no fact need), so a conflict on a fact cannot reach it; this copy lets the CGPA flow of
    row 6.21 run on the same route. Test data only: the playbook files are not touched."""
    data_ = yaml.safe_load((PLAYBOOK_DIR / "germany_master.v2.yaml").read_text(encoding="utf-8"))
    data_["version"] = 3
    data_["asks"][GPA] = {"stated": "Tell us your final CGPA", "which_is_right": "Which CGPA is right?"}
    for task in data_["tasks"]:
        if task["template_key"] in ("uni_assist_apply", "direct_apply"):
            task["needs"].append({"fact": GPA, "evidence": "stated"})
    return Playbook.model_validate(data_)


def seed_knowledge(kb: SqlKnowledge) -> None:
    def fact(value) -> Fact:
        return Fact(value, "q", "https://uni.example/x", CHECKED, 2027, "confirmed")

    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    load_seed(NEEDS_SEED, kb)  # the test calendar: the fictional matric result day (R-20)
    for ref in ("ie-p1", "ie-p2", "ie-p3", "ie-p4"):
        kb.upsert("programme", ref, "deadline_close", fact({"date": "2027-07-15"}), "manual")
    for ref in ("ie-p1", "ie-p2"):
        kb.upsert("programme", ref, "english_requirement", fact({"ielts": 6.5}), "manual")
    for ref in ("ie-p3", "ie-p4"):
        kb.upsert("programme", ref, "english_requirement", fact(False), "manual")
    for ref in ("pk-p1", "pk-i1"):
        kb.upsert("programme", ref, "merit_list_date", fact({"date": "2027-08-15"}), "manual")


@pytest.fixture
def world(engine, clean, os_db, tmp_path, monkeypatch):
    """PAI OS on its ports with the Counsellor module on, every part of the flow on, the mailer stubbed, a test clock."""
    from app.security import rate_limit
    from app.services import auth_emails

    clock, fake = Clock(), SimpleNamespace(client=FakeClient())
    books = {**load_playbook_dir(PLAYBOOK_DIR), **load_playbook_dir(FAKE_DIR), **load_playbook_dir(NEEDS_DIR)}
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true", "OS_ADMIN_TOKEN": TOKEN,
                              "OS_DBOS_SYSTEM_SCHEMA": __import__("tests.os.conftest", fromlist=["x"]).TEST_DBOS_SCHEMA})
    os_svc = make_services(settings, engine=engine, playbooks=books, today=lambda: clock.today,
                           dbos_client=lambda: fake.client, terms_dir=TEST_TERMS)
    kb = SqlKnowledge(engine, TENANT)
    seed_knowledge(kb)
    store = ProgrammeStore(engine, TENANT)
    load_programme_seed(PROGRAMME_SEED, store)
    for ref, route in (("ie-p1", "ireland_master"), ("ie-p2", "ireland_master"), ("ie-p3", "ireland_master"),
                       ("ie-p4", "ireland_master"), ("pk-p1", "pakistan_bs"), ("pk-i1", "pakistan_inter")):
        store.upsert(Programme(ref=ref, route_key=route, university="University", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://example.org/{ref}",), official_domains=("example.org",)))
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id=TENANT, enabled=True))
    ports.configure(os_svc, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice,
                    choice_sink_enabled=bridge.choice_enabled, student_facts=bridge.student_facts,
                    document_files=bridge.document_file_bytes, documents_enabled=bridge.documents_enabled,
                    on_document_deleted=bridge.on_os_document_deleted, fact_conflicts=bridge.fact_conflicts,
                    fact_answer=bridge.answer_fact_question)  # no post-commit hooks: the sweeps deliver
    rate_limit.reset()
    monkeypatch.setattr(auth_emails, "send_email", lambda to, subject, html, text_body=None: True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    for part in ("CONNECT_STUDENT_FACTS", "CONNECT_ONE_UPLOAD", "CONNECT_HANDOFF", "CONNECT_ROADMAP_FROM_PLANVIEW"):
        monkeypatch.setattr(config, part, True, raising=False)
    monkeypatch.setattr("app.routers.roadmap.resolve_human", lambda db, ws, auth: SimpleNamespace())
    previous = storage._store
    storage._store = storage.LocalFileStore(str(tmp_path / "files"))
    replanner = Replanner(engine, os_svc.plans, load_replan_configs(), Outbox(engine, TENANT),
                          clock=lambda: clock.now, escalations=os_svc.escalations)
    try:
        yield SimpleNamespace(svc=os_svc, engine=engine, os_db=os_db, settings=settings, kb=kb, box=clock, fake=fake,
                              replanner=replanner, books=books, client=None)
    finally:
        storage._store = previous
        ports.configure(None)
        rate_limit.reset()


# --- the student ---------------------------------------------------------------------------------------------------


def os_api(svc_):
    app = FastAPI()
    app.include_router(build_router(lambda: svc_), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    return TestClient(app)


class Student:
    """One signed-in student on the Counsellor app, and the same student on the OS HTTP API."""

    def __init__(self, world, client, who, params, auth):
        self.world, self.svc, self.client, self.who, self.params, self.auth = world, world.svc, client, who, params, auth
        self.os = os_api(world.svc)
        self.id = who.workspace_id
        self.me = {"X-Test-Student": self.id}
        self.before = chat_rows(who)

    # -- the OS API
    def requests(self, status=None, kind=None) -> list[dict]:
        got = self.os.get("/v1/os/requests", headers=self.me)
        assert got.status_code == 200, got.text
        return [r for r in got.json()["requests"] if (status is None or r["status"] == status)
                and (kind is None or r["kind"] == kind)]

    def request(self, ref, kind=None, status="open") -> dict:
        (found,) = [r for r in self.requests(status, kind) if r["need"]["ref"] == ref]
        return found

    def answer(self, request, choice, value=None, **over):
        body = {"ref": request["ref"], "seen": request["seen"], "choice": choice, **({"value": value} if value else {}),
                **over}
        return self.os.post(f"/v1/os/requests/{request['id']}/answer", json=body, headers=self.me)

    def inbox(self) -> dict:
        got = self.os.get("/v1/os/inbox", headers=self.me)
        assert got.status_code == 200, got.text
        return got.json()

    def agree(self):
        from app.os.consent import ConsentStore, current_terms

        ConsentStore(self.svc.engine, TENANT).agree(self.id, current_terms(self.svc.terms_dir).version)

    # -- the plan
    def plan_id(self) -> int:
        return Flow(self.svc, self.client, self.who, self.params).plan_id()

    def steps(self, plan_id=None) -> dict[str, str]:
        with self.svc.engine.connect() as conn:
            return {r.instance_key: r.state for r in conn.execute(select(T).where(T.c.plan_id == (plan_id or self.plan_id())))}

    def step(self, key, plan_id=None):
        with self.svc.engine.connect() as conn:
            return conn.execute(select(T).where(T.c.plan_id == (plan_id or self.plan_id()), T.c.instance_key == key)).one()

    def done(self, prefix, plan_id=None) -> list[str]:
        """The request steps that closed as done (a closed step is renamed `<key>#d...`, so the same ask can be made again)."""
        return [k for k, st in self.steps(plan_id).items() if k.startswith(prefix) and st == "done"]

    def open_steps(self, prefix="", plan_id=None) -> list[str]:
        return sorted(k for k, st in self.steps(plan_id).items() if k.startswith(prefix) and "#" not in k
                      and st not in ("done", "cancelled", "skipped"))

    def blocked(self, plan_id=None) -> dict[str, str | None]:
        with self.svc.engine.connect() as conn:
            return {r.instance_key: r.blocked_reason for r in conn.execute(select(T).where(
                T.c.plan_id == (plan_id or self.plan_id())))}

    def view(self) -> dict:
        return bridge.plan_view(self.id)

    def roadmap_steps(self) -> dict[str, dict]:
        return {s["key"]: s for s in chosen(self.client, self.params)["steps"]}

    def rows(self, status=None) -> list:
        with self.svc.engine.connect() as conn:
            return [r for r in conn.execute(select(models.student_requests).where(
                models.student_requests.c.student_ref == self.id).order_by(models.student_requests.c.id))
                if status is None or r.status == status]

    def row_of(self, need_ref, status="open"):
        (found,) = [r for r in self.rows(status) if r.need_ref == need_ref]
        return found

    # -- the Vault
    def say(self, key, value, **kw):
        """The student tells PAI a record (the Vault, `user_explicit`, evidence `stated`), then the Vault event is delivered."""
        with self.who.factory() as db:
            write(db, self.id, "student_record", key, value, **kw)
            bridge.deliver_pending(db, self.id)

    def deliver(self) -> dict:
        """Hands the pending fact proposals to the Vault's sink, runs the reconcile job inline on each candidate, then
        delivers the Vault events the accepted candidates raised."""
        with self.who.factory() as db:
            got = bridge.deliver_fact_proposals(db)
            for candidate in db.scalars(select(MemoryCandidate).where(MemoryCandidate.status == "pending")
                                        .order_by(MemoryCandidate.id)).all():
                MemoryReconciler(db).reconcile(candidate)
            db.commit()
            bridge.deliver_pending(db, self.id)
        return got

    def records(self, kind="education") -> list[dict]:
        from app.pai_c.memory import MemoryService

        with self.who.factory() as db:
            return list(MemoryService(db).profile(self.id).records[kind])

    def record_with(self, field) -> dict:
        (found,) = [r for r in self.records() if field in (r.get("result") or {})]
        return found

    def cards(self, status="open") -> list:
        with self.who.factory() as db:
            return list(db.scalars(select(ProfileIssue).where(ProfileIssue.status == status)
                                   .order_by(ProfileIssue.created_at)))

    # -- documents
    def upload(self, name, doc_type, content_type="image/png"):
        got = post_file(self.client, self.who, self.auth, name=name, data=sample(name), content_type=content_type,
                        doc_type=doc_type)
        assert got.status_code == 200, got.text
        return got.json()["data"]["os_document"]["id"]

    def upload_read(self, name, doc_type, values) -> int:
        """Uploads the sample through the one endpoint, then stores the reading the offline reader gives (the reader
        itself is run in `reader`; this is the same reading, without a worker, for the steps that only need the result)."""
        doc_id = self.upload(name, doc_type)
        simulate_read(self.svc.engine, doc_id, doc_type, values)
        return doc_id

    def fields_of(self, doc_id) -> dict:
        return {f["field"]: (f["value_confirmed"] if f["confirmed_at"] else f["value_read"])
                for f in DocumentStore(self.svc.engine, TENANT).fields(doc_id)}

    def confirm(self, doc_id, values=None):
        values = values if values is not None else self.fields_of(doc_id)
        return self.os.post(f"/v1/os/documents/{doc_id}/confirm", json={"fields": values}, headers=self.me)

    def confirmed(self, name, doc_type, values) -> int:
        doc_id = self.upload_read(name, doc_type, values)
        assert self.confirm(doc_id).status_code == 200
        return doc_id

    def reader_waits_for(self, doc_id, status="read", seconds=60):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if DocumentStore(self.svc.engine, TENANT).get(doc_id).status == status:
                return
            time.sleep(0.2)
        raise AssertionError(f"document {doc_id} is not {status}")

    # -- throughout
    def throughout(self) -> None:
        """Throughout (R-45, R-19, R-01, §9.3 rule 7): no chat row; one open request per fact; no value in a request row."""
        after = chat_rows(self.who)
        assert after == {t: self.before[t] for t in after}, after
        assert request_store.duplicates(self.svc.engine, TENANT) == []
        assert {c.name for c in models.student_requests.c} == FACT_COLUMNS  # no column can hold a value
        for row in self.rows():
            assert not {"value", "values", "answer"} & set(row._fields)


@contextmanager
def signed_in(world, entry):
    """`entry` is a roadmap student context (`germany_student()` / `pre_eng()`); the student gets a Firebase bearer, so
    the upload routes work on the same session as the roadmap routes."""
    with entry as (client, who, params):
        with who.factory() as db:
            token, identity = link_owner(db, db.get(User, who.user_id))
        with patch("app.database.new_session", lambda: who.factory()), \
                patch("app.database.SessionLocal", who.factory), \
                patch("app.routers.events.SessionLocal", who.factory), firebase_tokens({token: identity}):
            s = Student(world, client, who, params, {"Authorization": "Bearer " + token})
            s.agree()
            yield s


def choose(s, world, destination, refs, expect="planned"):
    data(choose_with(s.client, s.params, destination=destination, places=[{"ref": r, "rank": i + 1} for i, r in enumerate(refs)],
                     intake=WINTER))
    assert run_os(world.svc) == [(expect, None)]


def sweep_at(world, day: date) -> dict:
    """The clock moves to `day`: the deadline engine, the reminders, then the replan job (the workflow runs in this process)."""
    world.box.set(day)
    deadline_engine.run(world.svc.plans, world.engine)
    return sweep(world, world.box.now)


def reminders_of(world, task_id) -> list[str]:
    with world.engine.connect() as conn:
        return [k for k in conn.execute(select(models.outbox.c.idempotency_key).where(
            models.outbox.c.idempotency_key.like(f"reminder:{task_id}:%")).order_by(models.outbox.c.id)).scalars()]


def os_events(world, plan_id, type_):
    with world.engine.connect() as conn:
        return conn.execute(select(EV).where(EV.c.plan_id == plan_id, EV.c.type == type_).order_by(EV.c.id)).all()


SSC_VALUES = {"student_name": "Sara Ahmed Khan", "father_name": "Ahmed Raza Khan", "date_of_birth": "2001-04-12",
              "institution": "Exampleton Model School", "marks_obtained": 910, "marks_total": 1100}
HSSC_VALUES = {**SSC_VALUES, "marks_obtained": 910, "marks_total": 1100}


# --- row 6.19: Germany master, version 2 ---------------------------------------------------------------------------

APPLY = ("uni_assist_apply", "direct_apply")


def test_6_19_germany_v2_asks_for_the_certificates_and_blocks_the_applications(world):
    with signed_in(world, germany_student()) as s, level("master"):
        vault((s.client, s.who, s.params))
        s.before = chat_rows(s.who)
        # 1. choose with two places: planned on version 2
        choose(s, world, "DE", ["ovgu-eeit", "btu-artificial-intelligence"])
        plan_id = s.plan_id()
        with world.engine.connect() as conn:
            assert conn.execute(select(models.playbook_pins.c.version).where(
                models.playbook_pins.c.plan_id == plan_id)).scalar_one() == 2

        # 2. the two certificates are waiting; the applications are blocked on them, and the asks are dated from them
        steps = s.steps()
        asked = [k for k in steps if k.startswith("provide@")]
        assert sorted(asked) == [f"provide@document:{HSSC}:shown", f"provide@document:{SSC}:shown"]
        assert all(steps[k] == "waiting_student" for k in asked)
        blocked = s.blocked()
        apply_keys = [k for k in steps if k.split("@")[0] in APPLY]
        assert apply_keys  # an application step for each place whose route is open on the seed
        for k in apply_keys:
            assert steps[k] == "blocked" and blocked[k].startswith("awaiting_fact:"), (k, steps[k], blocked[k])
        for k in asked:
            assert s.step(k).due_at is not None  # dated backwards from the applications

        # 3. one open request per document, in the table, in the plan view, on the roadmap and in the inbox
        rows = s.rows("open")
        assert sorted((r.need_kind, r.need_ref, r.evidence, r.kind) for r in rows) == [
            ("document", HSSC, "shown", "provide"), ("document", SSC, "shown", "provide")]
        view = s.view()
        assert sorted(r["need"]["ref"] for r in view["requests"] if r["status"] == "open") == [HSSC, SSC]
        shown = s.roadmap_steps()
        for k in asked:
            assert shown[k]["tickable"] is False and shown[k]["request"]["kind"] == "provide"
            assert shown[k]["request"]["evidence"] == "shown" and shown[k]["request"]["text"]
        inbox_titles = {i["instance_key"] for i in s.inbox()["items"]}
        assert set(asked) <= inbox_titles
        assert sorted(r["need"]["ref"] for r in s.requests("open")) == [HSSC, SSC]
        # a request cannot be ticked, on either side
        for k in asked:
            done = s.os.post(f"/v1/os/inbox/{s.step(k).id}/complete", json={}, headers=s.me)
            assert done.status_code == 409, done.text
            assert s.steps()[k] == "waiting_student"
        ticked = post(s.client, s.params, "steps", {"key": asked[0], "done": True})
        assert ticked.status_code in (400, 404, 409, 422), ticked.text
        assert s.steps()[asked[0]] == "waiting_student"

        # 4. one reminder per step on the next hourly run, and the app is told once (`student_needed`)
        world.box.set(date(2027, 1, 21))
        run_reminders(world.engine, Outbox(world.engine, TENANT), world.box.now, TENANT)
        for k in asked:
            assert len(reminders_of(world, s.step(k).id)) == 1
        with world.engine.connect() as conn:
            told = conn.execute(select(models.outbox).where(models.outbox.c.template == "os_event")).all()
        # the app is told once for the whole plan: `plan_created` stands for the steps that open with it (R-45)
        assert [r.payload["kind"] for r in told if r.payload["plan_id"] == plan_id] == ["plan_created"]
        # no email twice: a second run in the same slot adds nothing
        before = {k: len(reminders_of(world, s.step(k).id)) for k in asked}
        run_reminders(world.engine, Outbox(world.engine, TENANT), world.box.now + timedelta(hours=1), TENANT)
        assert {k: len(reminders_of(world, s.step(k).id)) for k in asked} == before
        s.throughout()

        # 5. the student shows the two certificates (the one upload endpoint, confirmed): both requests close, the
        # applications are no longer blocked on them, and the reminders stop
        ssc = s.confirmed("b1_ssc_certificate.png", SSC, SSC_VALUES)
        assert len(s.done(f"provide@document:{SSC}:shown")) == 1 and s.row_of(SSC, "answered")
        assert s.steps().get(f"provide@document:{SSC}:shown") is None
        assert s.row_of(HSSC)  # the other is still asked
        assert all(s.blocked()[k] is not None for k in apply_keys)  # still waiting for the HSSC
        hssc = s.confirmed("b1_hssc_certificate.png", HSSC, HSSC_VALUES)
        assert ssc != hssc
        assert s.open_steps("provide@") == [] and len(s.done("provide@")) == 2
        assert s.rows("open") == [] and {r.closed_cause for r in s.rows("answered")} == {"request_answered"}
        assert all(not (s.blocked()[k] or "").startswith("awaiting_fact") for k in apply_keys)
        assert s.view()["requests"] == [r for r in s.view()["requests"] if r["status"] != "open"]
        s.throughout()
