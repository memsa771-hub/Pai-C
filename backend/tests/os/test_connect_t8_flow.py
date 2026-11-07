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
        self.set(day)

    def set(self, day: date) -> None:
        self.today = day
        self.now = datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=8)


def germany_v3_with_a_gpa_need() -> Playbook:
    """The shipped Germany v2 plus one need, the CGPA at `stated`, on the two application steps. The shipped version 2 asks
    only for documents (it has no fact need), so a conflict on a fact cannot reach it; this copy lets the CGPA flow of
    row 6.21 run on the same route. Test data only: the playbook files are not touched."""
    data_ = yaml.safe_load((PLAYBOOK_DIR / "germany_master.v2.yaml").read_text(encoding="utf-8"))
    data_["version"] = 3
    data_["asks"][GPA] = {"stated": "Tell us your final CGPA", "which_is_right": "Which CGPA is right?",
                          "citations": data_["asks"][SSC]["citations"]}
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
    inflate = {"on": False}

    def facts(ref):
        """The real StudentFacts; with `inflate` on, a mark of 1000 reads 1200 (the Vault itself refuses to hold a mark
        above its total, so the OS's own check is shown the one way it can arise: a reading the Vault would not accept)."""
        built = bridge.student_facts(ref)
        if built and inflate["on"]:
            for f in built["facts"]:
                if f["key"] == INTER_MARKS and f["value"] == 1000:
                    f["value"] = 1200
        return built

    ports.configure(os_svc, choice_enabled=bridge.choice_enabled, choice_sink=bridge.request_choice,
                    choice_sink_enabled=bridge.choice_enabled, student_facts=facts,
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
                              replanner=replanner, books=books, client=None, inflate=inflate)
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

    def row_of(self, need_ref, status="open", kind=None):
        (found,) = [r for r in self.rows(status) if r.need_ref == need_ref and (kind is None or r.kind == kind)]
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

    def files(self) -> list:
        with self.who.factory() as db:
            return list(db.scalars(select(FileRecord).where(FileRecord.workspace_id == self.id).order_by(FileRecord.created_at)))

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


def tick(world, day: date) -> None:
    """The clock moves to `day`: the hourly deadline recompute and the reminders (no replan job: no workflow is running)."""
    world.box.set(day)
    deadline_engine.run(world.svc.plans, world.engine)
    run_reminders(world.engine, Outbox(world.engine, TENANT), world.box.now, TENANT)


def replan_only(world, now: datetime) -> dict[int, dict]:
    """One replan job at `now`, without the reminders run (the hourly jobs are separate: the deadline engine and the replan
    job can run before the reminders of the same day), then the workflows it queued run to the end."""
    from app.os.replan.run import generation, replan_workflow_id

    world.box.now = now
    queued = [(e.plan_id, e.id) for e in events.pending(world.engine, TENANT)
              if not world.replanner.plans.kernel.changes_paused(e.plan_id)]
    assert run_replan_job(world.replanner, world.client, now) == len(queued)
    return {i: world.client.retrieve_workflow(replan_workflow_id(TENANT, p, i, generation(world.engine, TENANT, p))).get_result()
            for p, i in queued}


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


@contextmanager
def reader(world):
    """The OS document worker, in this process: DBOS on the test schema, the offline reader answering from the committed
    sample documents, the file read through the host adapter. Swaps the OS's DBOS client for the real one."""
    from dbos import DBOS, DBOSClient

    from app.os.agents.offline import offline_model
    from app.os.agents.spec import AGENT_DIR, load_agent_spec
    from app.os.documents.checks import load_name_variants
    from app.os.documents.reader import build_readers
    from app.os.documents.run import register_documents
    from app.os.documents.types import load_document_types
    from app.os.kernel import Kernel
    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow
    from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema

    answers = HERE / "rehearsal" / "answers"
    types, spec = load_document_types(), load_agent_spec(AGENT_DIR / "documents.v1.yaml")
    reset_dbos_schema(world.os_db)
    settings = load_settings({"OS_DATABASE_URL": world.os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA,
                              "OS_MODEL_MODE": "offline", "OS_REHEARSAL": "on", "OS_OFFLINE_ANSWERS_DIR": str(answers)})
    readers = build_readers(offline_model("documents", answers), types, spec)
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(world.engine, settings, default_registry(), Kernel(world.engine, TENANT))
    register_documents(world.engine, settings, readers, spec, types, load_name_variants())
    launch()
    client = DBOSClient(system_database_url=world.os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    world.fake.client = client
    try:
        yield client
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)
        world.fake.client = FakeClient()


# --- rows 6.20 (the mechanism), R-18, R-19: the fake Pakistan intermediate route, version 2 --------------------------

MATRIC = {"qualification_name": "matric", "academic_status": "completed", "institution_name": "Exampleton Model School",
          "result": {"marks_obtained": 910, "marks_total": 1100}}
RESULT_DAY = date(2027, 4, 30)  # the test calendar (`needs_seed.yaml`): the fictional matric result day


def test_6_20_result_expected_then_provide_then_stated_then_shown(world):
    with signed_in(world, pre_eng()) as s, level("intermediate"):
        vault((s.client, s.who, s.params))
        s.before = chat_rows(s.who)
        choose(s, world, "PK", ["pk-i1"])
        plan_id = s.plan_id()
        obtained, total = f"provide@fact:{MATRIC_MARKS}:stated", f"provide@fact:{MATRIC_TOTAL}:stated"
        shown = f"provide@fact:{MATRIC_MARKS}:shown"
        expected = f"result_expected@fact:{MATRIC_MARKS}"

        # 1. before the calendar date: a step that waits for the result, due that day; then a pending provide step
        # with an open request row (R-20); nothing is asked of the student yet for the marks
        steps = s.steps()
        assert steps[expected] == "blocked" and s.blocked()[expected] == f"result_expected:{MATRIC_MARKS}"
        due = s.step(expected).due_at
        assert due.date() == RESULT_DAY  # the test calendar's day, in the route's zone
        assert steps[obtained] == "pending" and steps[total] == "waiting_student"  # the total has no calendar: asked now
        assert s.step(obtained).due_at is not None
        assert {r.need_ref for r in s.rows("open")} == {MATRIC_MARKS, MATRIC_TOTAL}  # a row for the pending step too
        assert s.row_of(MATRIC_MARKS).kind == "provide" and s.row_of(MATRIC_MARKS).evidence == "stated"
        assert s.row_of(MATRIC_MARKS).task_id == s.step(obtained).id
        assert steps["admission_form"] == "blocked" and steps[f"merit_list@pk-i1"] == "blocked"
        # the roadmap shows the result line and the request line, neither tickable
        road = s.roadmap_steps()
        assert road[expected]["request"]["kind"] == "result_expected" and road[expected]["tickable"] is False
        assert road[obtained]["request"]["kind"] == "provide" and road[obtained]["tickable"] is False
        assert [r["need"]["ref"] for r in s.requests("open")] == sorted([MATRIC_MARKS, MATRIC_TOTAL])  # both listed, with dates
        # an hourly run before the date asks nothing more and makes no ladder event
        tick(world, date(2027, 2, 1))
        assert s.steps()[obtained] == "pending" and os_events(world, plan_id, "document_missing") == []

        # 2. the clock moves past the date: the result step goes, the provide step waits, the student is told
        tick(world, RESULT_DAY + timedelta(days=2))
        steps = s.steps()
        assert expected not in steps or steps[expected] in ("done", "cancelled")
        assert steps[obtained] == "waiting_student"
        with world.engine.connect() as conn:
            told = [r.payload for r in conn.execute(select(models.outbox).where(models.outbox.c.template == "os_event"))]
        assert any(p["kind"] == "student_needed" and p.get("instance_key") == obtained for p in told)
        assert len(s.rows("open")) == 2  # still one open row per fact: the same rows, not new ones

        # 3. the student types the marks in chat (the Vault, stated): the stated step is done, its row answered,
        # the form is no longer blocked; the shown step and its row are open and the merit list stays blocked
        s.say("education", MATRIC)
        steps = s.steps()
        assert obtained not in steps and total not in steps
        assert len(s.done(obtained)) == 1 and len(s.done(total)) == 1
        assert {r.need_ref for r in s.rows("answered")} == {MATRIC_MARKS, MATRIC_TOTAL}
        assert {r.closed_cause for r in s.rows("answered")} == {"request_answered"}
        assert steps["admission_form"] != "blocked" and not s.blocked()["admission_form"]
        assert steps[shown] == "waiting_student" and steps["merit_list@pk-i1"] == "blocked"
        assert s.blocked()["merit_list@pk-i1"].startswith("awaiting_fact:")
        (only,) = [r for r in s.rows("open")]
        assert (only.need_ref, only.evidence, only.kind) == (MATRIC_MARKS, "shown", "provide")  # one open row for the fact
        assert [r["need"]["ref"] for r in s.requests("open")] == [MATRIC_MARKS]
        # the student has not been asked twice: the stated step is gone from the inbox
        assert obtained not in {i["instance_key"] for i in s.inbox()["items"]}

        # 4. the student uploads and confirms the matric certificate (the offline reader reads the committed sample):
        # the Vault holds the fact as shown, the shown step is done and the merit list is ready
        with reader(world):
            doc_id = s.upload("b1_ssc_certificate.png", SSC)
            s.reader_waits_for(doc_id, "read")
        values = s.fields_of(doc_id)
        assert (values["marks_obtained"], values["marks_total"]) == (910, 1100)
        assert s.confirm(doc_id).status_code == 200
        assert s.deliver()["written"] == 1
        record = s.record_with("marks_obtained") if False else [r for r in s.records()
                                                               if (r.get("result") or {}).get("marks_obtained") == 910][0]
        assert record["evidence_level"] == "shown"
        assert s.cards() == []  # the same value: nothing to ask
        assert len(s.done(shown)) == 1 and s.open_steps("provide@") == []
        assert s.rows("open") == []
        assert not s.blocked()["merit_list@pk-i1"]  # nothing is awaited from the student's data any more...
        assert s.steps()["merit_list@pk-i1"] == "blocked"  # ...only the form, which is the student's own step
        ticked = s.os.post(f"/v1/os/inbox/{s.step('admission_form').id}/complete", json={}, headers=s.me)
        assert ticked.status_code == 200 and ticked.json() == {"completed": True}
        assert s.steps()["admission_form"] == "done" and s.steps()["merit_list@pk-i1"] == "waiting_student"
        s.throughout()


# --- row 6.21: Germany, the CGPA the student said and the CGPA a transcript shows -------------------------------------

STATED_CGPA = {"qualification_name": "bachelor", "academic_status": "completed", "result": {"gpa": 3.4, "gpa_scale": 4.0}}
WHICH_GPA = f"which_is_right@fact:{GPA}:stated"
TRANSCRIPT_FILE = "b2_transcript.png"  # the sample key: CGPA 3.2 on a scale of 4.0


def vault_post(s, card, answer):
    return s.client.post(f"/v1/vault/conflicts/{card.id}/resolve?network={s.id}", headers=s.auth, json={"answer": answer})


def transcript_read(world, s) -> int:
    """Uploads the sample transcript typed, and waits for the offline reader."""
    with reader(world):
        doc_id = s.upload(TRANSCRIPT_FILE, TRANSCRIPT_DOC)
        s.reader_waits_for(doc_id, "read")
    assert s.fields_of(doc_id)["cgpa"] == 3.2
    return doc_id


def germany_with_a_stated_cgpa(world, s) -> int:
    """The student said CGPA 3.4 in chat and chose two places in Germany; the plan is on the version that asks for the CGPA."""
    world.svc.plans.playbooks[("germany_master", 3)] = germany_v3_with_a_gpa_need()
    vault((s.client, s.who, s.params))
    s.before = chat_rows(s.who)
    choose(s, world, "DE", ["ovgu-eeit", "btu-artificial-intelligence"])
    plan_id = s.plan_id()
    with world.engine.connect() as conn:
        assert conn.execute(select(models.playbook_pins.c.version).where(
            models.playbook_pins.c.plan_id == plan_id)).scalar_one() == 3
    ask = f"provide@fact:{GPA}:stated"  # the CGPA is missing: asked, and the applications wait for it
    assert s.steps()[ask] == "waiting_student" and s.row_of(GPA).kind == "provide"
    assert all(s.blocked()[k].startswith("awaiting_fact:") for k in s.steps()
               if k.split("@")[0] in APPLY)
    s.say("education", STATED_CGPA)  # the student tells PAI in chat: the Vault holds it as stated
    assert s.record_with("gpa")["evidence_level"] == "stated"
    assert s.steps().get(ask) is None and len(s.done(ask)) == 1 and s.row_of(GPA, "answered")
    assert not [k for k in s.steps() if "bachelor.gpa" in k and "#" not in k]  # stated: nothing asked, no question
    return plan_id


def the_conflict_is_asked(world, s, plan_id) -> dict:
    """The transcript is confirmed: the Vault opens one card (3.4 stated, 3.2 shown); the hourly recompile turns it into one
    which-is-right request and pauses the steps that use the CGPA."""
    doc_id = transcript_read(world, s)
    assert s.confirm(doc_id).status_code == 200
    assert s.deliver()["written"] == 1
    assert s.record_with("gpa")["result"]["gpa"] == 3.4  # a document never overwrites a stated value
    (card,) = s.cards()
    assert card.evidence["current"]["result"]["gpa"] == 3.4 and card.evidence["proposed"]["result"]["gpa"] == 3.2
    assert WHICH_GPA not in s.steps()  # nothing yet: the OS has not looked since the card opened
    tick(world, world.box.today)  # the hourly deadline recompute
    steps = s.steps()
    assert steps[WHICH_GPA] == "waiting_student" and s.step(WHICH_GPA).inbox_kind == "choose"
    apply_keys = [k for k in steps if k.split("@")[0] in APPLY]
    assert apply_keys
    for k in apply_keys:  # paused with the reason
        assert steps[k] == "blocked" and s.blocked()[k] == f"which_is_right:{GPA}", (k, s.blocked()[k])
    (asked,) = s.requests("open", "which_is_right")
    assert asked["need"] == {"kind": "fact", "ref": GPA, "evidence": "stated"}
    return asked


def closed_everywhere(world, s, asked, plan_id, reminders_before: int) -> None:
    """Answered anywhere closes everywhere (R-19, Review Focus 3): the step is done, the row answered, the inbox does not list
    it, no further reminder is written, and the plan view shows it answered."""
    assert WHICH_GPA not in s.steps() and len(s.done(WHICH_GPA)) == 1
    row = [r for r in s.rows("answered") if r.need_ref == GPA and r.kind == "which_is_right"]
    assert len(row) == 1 and row[0].closed_cause == "request_answered" and not [r for r in s.rows("open") if r.need_ref == GPA]
    assert not [i for i in s.inbox()["items"] if i["instance_key"].startswith("which_is_right@")]
    assert s.requests("open", "which_is_right") == []
    assert [r["status"] for r in s.requests(None, "which_is_right")] == ["answered"]
    assert [r["status"] for r in s.view()["requests"] if r["need"]["ref"] == GPA and r["request_id"] == asked["id"]] == [
        "answered"]
    run_reminders(world.engine, Outbox(world.engine, TENANT), world.box.now + timedelta(days=3), TENANT)
    assert len(reminders_of(world, asked["task_id"])) == reminders_before  # no reminder after it closed
    assert not any((b or "").startswith("which_is_right:") for b in s.blocked().values())  # the steps resume
    assert s.cards() == []


def test_6_21_germany_the_two_values_are_shown_and_the_answer_goes_to_the_vault(world):
    with signed_in(world, germany_student()) as s, level("master"):
        plan_id = germany_with_a_stated_cgpa(world, s)
        asked = the_conflict_is_asked(world, s, plan_id)
        # what the student sees: both values, each with its source and level (read live from the Vault, never stored)
        current, proposed = asked["choices"]
        assert (current["choice"], current["value"], current["source"]["kind"], current["source"]["evidence"]) == (
            "current", 3.4, "vault", "stated")
        assert (proposed["choice"], proposed["value"], proposed["source"]["kind"], proposed["source"]["evidence"]) == (
            "proposed", 3.2, "document", "shown")
        assert proposed["source"]["document_ref"] == s.files()[-1].id
        assert asked["allow_new"] is True and asked["how"] and asked["title"]
        stored = [tuple(r) for r in s.rows()]
        assert all(3.4 not in r and 3.2 not in r for r in stored)  # R-01: the OS keeps no value
        # a reminder is written for the question while it waits
        tick(world, world.box.today + timedelta(days=1))
        before = len(reminders_of(world, asked["task_id"]))
        assert before >= 1
        # the roadmap shows the request line, not tickable
        road = s.roadmap_steps()[WHICH_GPA]
        assert road["tickable"] is False and road["request"]["kind"] == "which_is_right"
        # answer `proposed`: the Vault holds 3.2, written as the student's explicit choice with the request in its evidence
        got = s.answer(asked, "proposed")
        assert got.status_code == 200 and got.json() == {"status": "answered"}
        assert s.record_with("gpa")["result"]["gpa"] == 3.2 and s.record_with("gpa")["evidence_level"] == "stated"
        with s.who.factory() as db:
            written = db.scalars(select(MemoryCandidate).where(MemoryCandidate.input_channel == "profile")
                                 .order_by(MemoryCandidate.created_at.desc())).first()
            assert written.source_type == "user_explicit" and written.evidence["capture"] == "os_which_is_right"
            assert written.evidence["os_request_id"] == asked["id"]
        closed_everywhere(world, s, asked, plan_id, before)
        s.throughout()


def test_6_21_second_student_answers_current_on_the_vault_page_and_the_step_closes_in_the_same_delivery(world):
    with signed_in(world, germany_student()) as s, level("master"):
        plan_id = germany_with_a_stated_cgpa(world, s)
        asked = the_conflict_is_asked(world, s, plan_id)
        tick(world, world.box.today + timedelta(days=1))
        reminders = len(reminders_of(world, asked["task_id"]))
        (card,) = s.cards()
        with s.who.factory() as db:
            before = db.scalar(select(func.count()).select_from(OsOutbox).where(OsOutbox.kind == "vault_event"))
        assert vault_post(s, card, "keep_current").status_code == 200
        assert s.row_of(GPA, "open").kind == "which_is_right"  # the OS has not heard yet
        with s.who.factory() as db:
            events_ = db.scalars(select(OsOutbox).where(OsOutbox.kind == "vault_event")).all()
            assert len(events_) == before + 1  # nothing was written to the Vault, yet the close raised its event
            assert GPA in max(events_, key=lambda r: r.payload["vault_version"]).payload["keys"]
            assert bridge.deliver_pending(db, s.id)["failed"] == 0  # one delivery: the OS recompiles and the step is done
        assert s.record_with("gpa")["result"]["gpa"] == 3.4  # the Vault keeps the student's value
        closed_everywhere(world, s, asked, plan_id, reminders)
        s.throughout()


def test_6_21_a_chat_answer_closes_the_step_through_the_close_hook_and_the_vault_event(world):
    """The transcript is read first (it answers the CGPA request, as shown); the student then says another number in the
    chat (a conversation candidate: a card opens, the document is the current value); the student's chat answer is the
    Operator's `profile_conflict` resume, which resolves the card through `ProfileIssueService` (the close hook)."""
    from app.memory.candidates import MemoryCandidateService
    from app.memory.profile_issues import ProfileIssueService

    with signed_in(world, germany_student()) as s, level("master"):
        world.svc.plans.playbooks[("germany_master", 3)] = germany_v3_with_a_gpa_need()
        vault((s.client, s.who, s.params))
        s.before = chat_rows(s.who)
        choose(s, world, "DE", ["ovgu-eeit", "btu-artificial-intelligence"])
        plan_id = s.plan_id()
        ask = f"provide@fact:{GPA}:stated"
        assert s.steps()[ask] == "waiting_student"
        # 1. an upload and confirm answers the request (the document is `shown`, which meets `stated`)
        doc_id = transcript_read(world, s)
        assert s.confirm(doc_id).status_code == 200 and s.deliver()["written"] == 1
        assert len(s.done(ask)) == 1 and s.row_of(GPA, "answered").kind == "provide"
        assert s.record_with("gpa")["evidence_level"] == "shown" and s.cards() == []
        # 2. the student says 3.4 in the chat: the Vault keeps the document's value and opens one card
        with s.who.factory() as db:
            said = MemoryCandidateService(db).propose(
                s.id, "student_record", key="education", proposed_value={"result": {"gpa": 3.4}}, confidence=0.9,
                source_type="conversation", input_channel="conversation",
                entities={"record_id": s.record_with("gpa")["id"]}, evidence={"quote": "my CGPA is 3.4"})
            assert MemoryReconciler(db).reconcile(said).outcome == "needs_review"
            db.commit()
        (card,) = s.cards()
        tick(world, world.box.today)
        asked = s.request(GPA, "which_is_right")
        current, proposed = asked["choices"]
        assert (current["value"], current["source"]["kind"], current["source"]["evidence"]) == (3.2, "document", "shown")
        assert (proposed["value"], proposed["source"]["kind"], proposed["source"]["evidence"]) == (3.4, "said", "stated")
        assert s.steps()[WHICH_GPA] == "waiting_student"
        tick(world, world.box.today + timedelta(days=1))
        reminders = len(reminders_of(world, asked["task_id"]))
        # 3. the student answers in the chat: the Operator resolves the card; the hook raises the Vault version
        with s.who.factory() as db:
            result = ProfileIssueService(db).resolve(s.id, card.id, "accept_proposed", note="Answered in the chat")
            assert result["resolved"]
            db.commit()
            assert bridge.deliver_pending(db, s.id)["failed"] == 0
        assert s.record_with("gpa")["result"]["gpa"] == 3.4
        closed_everywhere(world, s, asked, plan_id, reminders)
        s.throughout()


# --- an impossible value: marks above their total ---------------------------------------------------------------------


def test_an_impossible_value_is_asked_and_the_new_value_goes_to_the_vault(world):
    from app.os.requests import texts

    with signed_in(world, pre_eng()) as s, level("bachelor"):
        vault((s.client, s.who, s.params))
        s.before = chat_rows(s.who)
        (fsc,) = s.records()
        choose(s, world, "PK", ["pk-p1"])
        plan_id = s.plan_id()
        ask = f"provide@fact:{INTER_MARKS}:stated"
        assert s.steps()[ask] == "waiting_student"  # the marks are not held yet
        # 1. the student tells PAI 1000 of 1100: the request closes and the entry test is free of it
        s.say("education", {"result": {"marks_obtained": 1000, "marks_total": 1100}}, entities={"record_id": fsc["id"]})
        assert len(s.done(ask)) == 1 and s.blocked()["entry_test"] != f"awaiting_fact:{INTER_MARKS}"
        # 2. the OS reads that mark as 1200 of 1100 (see `facts`): the value cannot be right, so it is asked
        world.inflate["on"] = True
        tick(world, world.box.today)
        which = f"which_is_right@fact:{INTER_MARKS}:stated"
        assert s.steps()[which] == "waiting_student"
        assert s.blocked()["entry_test"] == f"which_is_right:{INTER_MARKS}"
        asked = s.request(INTER_MARKS, "which_is_right")
        assert asked["choices"] == [] and asked["allow_new"] is True and asked["how"] == texts.text("how_impossible")
        assert s.answer(asked, "current").status_code == 422  # there is no value to keep: only a new one is taken
        assert s.answer(asked, "new", "abc").status_code == 422
        assert s.answer(asked, "new", "9999").status_code == 422  # above the total
        assert s.row_of(INTER_MARKS).kind == "which_is_right"
        # 3. a new value: the Vault is updated through the reconciler as the student's explicit word, the step is done
        got = s.answer(asked, "new", "950")
        assert got.status_code == 200 and got.json() == {"status": "answered"}
        record = s.record_with("marks_obtained")
        assert record["result"]["marks_obtained"] == 950 and record["result"]["marks_total"] == 1100
        assert record["evidence_level"] == "stated"
        with s.who.factory() as db:
            written = db.scalars(select(MemoryCandidate).order_by(MemoryCandidate.created_at.desc())).first()
            assert written.evidence["capture"] == "os_which_is_right" and written.source_type == "user_explicit"
            assert written.evidence["os_request_id"] == asked["id"]
        assert len(s.done(which)) == 1 and which not in s.steps()
        assert s.row_of(INTER_MARKS, "answered", "which_is_right").closed_cause == "request_answered"
        assert not any((b or "").startswith("which_is_right:") for b in s.blocked().values())
        assert s.requests("open", "which_is_right") == []
        s.throughout()


# --- row 6.22: the fake Ireland route, version 2: the unanswered ladder ---------------------------------------------------

IE_ENGLISH = f"provide@fact:{IELTS}:shown"
IE_TRANSCRIPT = f"provide@document:{TRANSCRIPT_DOC}:shown"
DUE = date(2027, 7, 15)  # the fictional deadline of every place (`seed_knowledge`)
THREE = ["ie-p1", "ie-p2", "ie-p3"]


def test_6_22_ireland_the_ladder_reminders_at_risk_proposal_and_a_support_case(world):
    from tests.os.test_connect_t6_flow import at_chosen, journey_stage, places_of_plan
    from tests.os.test_unanswered_ladder import counsellor_rows, ladder_cases, never_silent, plan_status

    with signed_in(world, germany_student()) as s, level("master"), running(world):
        vault((s.client, s.who, s.params))
        s.before = chat_rows(s.who)
        choose(s, world, "IE", THREE)
        plan_id = s.plan_id()
        f = Flow(world.svc, s.client, s.who, s.params)
        at_chosen(f)
        with world.engine.connect() as conn:
            assert conn.execute(select(models.playbook_pins.c.version).where(
                models.playbook_pins.c.plan_id == plan_id)).scalar_one() == 2
        # 1. two requests: the transcript for every place, the English score for the two places that ask for it
        steps = s.steps()
        assert steps[IE_TRANSCRIPT] == "waiting_student" and steps[IE_ENGLISH] == "waiting_student"
        assert {r.need_ref for r in s.rows("open")} == {TRANSCRIPT_DOC, IELTS}
        english_due, transcript_due = s.step(IE_ENGLISH).due_at, s.step(IE_TRANSCRIPT).due_at
        print("DUES", english_due, transcript_due)
        assert english_due is not None and transcript_due is not None  # both are dated (english_proof is dated now)
        blocked = s.blocked()
        assert blocked["english_proof@ie-p1"] == f"awaiting_fact:{IELTS}" and "english_proof@ie-p3" not in steps

        # 2. the reminders follow the cadence: weekly far away, every third day nearer, daily in the last week
        def new_slots(day: date) -> list[str]:
            before = len(reminders_of(world, s.step(IE_ENGLISH).id))
            tick(world, day)
            return [k.split(":", 2)[2] for k in reminders_of(world, s.step(IE_ENGLISH).id)[before:]]

        far, near, last = new_slots(DUE - timedelta(days=60)), new_slots(DUE - timedelta(days=13)), new_slots(DUE - timedelta(days=5))
        assert [x.split(":")[0] for x in far] == ["w"] and [x.split(":")[0] for x in near] == ["d3"] \
            and [x.split(":")[0] for x in last] == ["d"]
        assert new_slots(DUE - timedelta(days=5)) == []  # the same day again adds nothing
        assert os_events(world, plan_id, "document_missing") == []  # not late yet
        # 3. the deadline is close and the English score is still missing: the request is nudged first (at risk)
        world.box.set(DUE - timedelta(days=1))  # a day before the deadline: no room left for the step's two days
        deadline_engine.run(world.svc.plans, world.engine)
        replan_only(world, world.box.now)  # the hourly replan job; the reminders run later in the day
        # (the English step is off the critical path here: the transcript is on it, so it is the request that is nudged)
        risky = event_of(world, plan_id, "deadline_at_risk", "apply@ie-p1")
        nudge = world.replanner.proposals.for_event(risky.id)
        assert nudge.status == "applied" and not nudge.big
        assert [(o["op"], o["instance_key"]) for o in nudge.ops] == [("reprioritise", IE_TRANSCRIPT),
                                                                    ("request_from_student", IE_TRANSCRIPT)]
        assert pending_proposals(world, plan_id) == [] and os_events(world, plan_id, "document_missing") == []
        with world.engine.connect() as conn:  # the Counsellor and the app are told of the risk
            told = [r.payload["kind"] for r in conn.execute(select(models.outbox).where(models.outbox.c.template == "os_event"))]
        assert "deadline_at_risk" in told

        # 4. the dates pass: the English request goes to a proposal (swap or drop the places that ask for it), the
        # transcript request (every place) goes to a support case for a person; reminders come first every time
        results = sweep(world, world.box.now + timedelta(hours=1))
        english, transcript = (event_of(world, plan_id, "document_missing", k) for k in (IE_ENGLISH, IE_TRANSCRIPT))
        assert results[english.id]["status"] == "pending" and results[transcript.id]["status"] == "applied"
        (proposal,) = pending_proposals(world, plan_id)
        assert proposal.big and proposal.event_ids == [english.id]
        assert {(o["op"], o.get("out_ref") or o["programme_ref"]) for o in proposal.ops} <= {
            ("swap_programme", "ie-p1"), ("swap_programme", "ie-p2"), ("cancel_programme", "ie-p1"),
            ("cancel_programme", "ie-p2")}  # only the places that ask for English; ie-p3 asks nothing of the student
        assert {o.get("out_ref") or o["programme_ref"] for o in proposal.ops} == {"ie-p1", "ie-p2"}
        support = SupportStore(world.engine, TENANT)
        case_e, case_t = support.for_event(english.id), support.for_event(transcript.id)
        assert case_e.reason == texts.text("unanswered_proposed") and case_e.proposal_id == proposal.id
        assert case_t.reason == texts.text("unanswered_all") and case_t.proposal_id != proposal.id
        for case in (case_e, case_t):  # PAI only: nobody is sent to choose again, the plan is not paused (Ruling problem 11)
            assert counsellor_rows(world, case.id) == [] and case.counsellor_status is None
        assert plan_status(world, plan_id) != "paused" and not world.svc.plans.kernel.changes_paused(plan_id)
        assert journey_stage(f) == "CHOSEN"
        assert never_silent(world, plan_id, world.box.now) == 2  # both requests, both with a proposal or a case
        assert places_of_plan(f) == THREE  # nothing is removed by itself
        with s.who.factory() as db:
            assert bridge.sweep_once(db)["sent"] == 0  # nothing reaches the Counsellor's escalation endpoint
        assert journey_stage(f) == "CHOSEN"

        # 5. the student accepts the proposal: the OS asks the Counsellor (T6), which writes the next version; the plan is
        # revised without the places that asked for the English score
        print("OPS", [(o["op"], o.get("out_ref") or o["programme_ref"], o.get("in_ref")) for o in proposal.ops])
        world.replanner.accept(s.id, proposal.id)
        assert world.replanner.proposals.get(proposal.id).status == "requested"
        assert places_of_plan(f) == THREE and f.versions() == [1]
        bridge.deliver_choice_request_now(choice_requests.key_of(proposal.id))
        assert f.versions() == [1, 2]
        assert {p["programme_ref"] for p in f.decision(2).places}.isdisjoint({"ie-p2"})
        assert run_os(world.svc) == [("revised", None)]
        assert world.replanner.proposals.get(proposal.id).status == "accepted"
        now_places = places_of_plan(f)
        assert "ie-p2" not in now_places and "ie-p3" in now_places and "ie-p1" not in now_places
        # the English request is no longer needed: its step and its row are cancelled, not "answered"; the transcript
        # request stays open, still one row, still unanswered
        assert IE_ENGLISH not in s.steps() and not s.done(IE_ENGLISH)
        assert [r.closed_cause for r in s.rows("cancelled") if r.need_ref == IELTS]
        assert not [r for r in s.rows("answered") if r.need_ref == IELTS]
        assert [r.need_ref for r in s.rows("open")] == [TRANSCRIPT_DOC]
        assert s.steps()[IE_TRANSCRIPT] == "waiting_student"
        assert plan_status(world, plan_id) != "paused" and journey_stage(f) == "CHOSEN"

        # 6. the transcript is still not shown: the plan is not stuck and not silent; the reminders go on, and the case stands
        before = len(reminders_of(world, s.step(IE_TRANSCRIPT).id))
        sweep_at(world, world.box.today + timedelta(days=1))
        assert len(reminders_of(world, s.step(IE_TRANSCRIPT).id)) == before + 1
        assert never_silent(world, plan_id, world.box.now) == 1
        assert len(ladder_cases(world, plan_id)) == 2  # one case per request, none more
        assert plan_status(world, plan_id) != "paused" and journey_stage(f) == "CHOSEN"
        s.throughout()


# --- the upgrade: a version-1 plan moves to version 2 only through the student's own accept ---------------------------------


def germany_with_the_gate_off(world, s) -> int:
    """A Germany master plan made while the needs gate is off (`CONNECT_STUDENT_FACTS` off): version 1, no request."""
    vault((s.client, s.who, s.params))
    s.before = chat_rows(s.who)
    with patch.object(config, "CONNECT_STUDENT_FACTS", False):
        choose(s, world, "DE", ["ovgu-eeit", "btu-artificial-intelligence"])
        plan_id = s.plan_id()
        assert s.os.get("/v1/os/requests", headers=s.me).status_code == 404
        assert s.os.get("/v1/os/inbox", headers=s.me).status_code == 200
    return plan_id


def pinned(world, plan_id) -> int:
    with world.engine.connect() as conn:
        return conn.execute(select(models.playbook_pins.c.version).where(models.playbook_pins.c.plan_id == plan_id)).scalar_one()


def test_a_version_1_plan_is_upgraded_only_by_an_accepted_proposal(world):
    from tests.os.test_connect_t6_flow import places_of_plan  # noqa: F401

    with signed_in(world, germany_student()) as s, level("master"), running(world):
        plan_id = germany_with_the_gate_off(world, s)
        assert pinned(world, plan_id) == 1
        before = s.steps()
        assert "school_certificates" in before and not [k for k in before if k.startswith("provide@")]
        assert s.rows() == [] and s.view()["requests"] == [] and all(x["needs"] == [] for x in s.view()["steps"])
        # the gate goes on (the Counsellor's part is switched on): nothing moves by itself, one proposal appears
        world.box.set(world.box.today + timedelta(days=1))
        assert run_replan_job(world.replanner, world.client, world.box.now) == 1  # records `playbook_newer`, queues the replan
        assert pinned(world, plan_id) == 1 and s.rows() == []
        newer = os_events(world, plan_id, "playbook_newer")
        assert len(newer) == 1 and (newer[0].payload["version"], newer[0].payload["from"]) == (2, 1)
        deadline = time.time() + 60
        while not pending_proposals(world, plan_id) and time.time() < deadline:
            time.sleep(0.2)
        (proposal,) = pending_proposals(world, plan_id)
        assert proposal.big and [o["op"] for o in proposal.ops] == ["upgrade_playbook"] and proposal.event_ids == [newer[0].id]
        run_replan_job(world.replanner, world.client, world.box.now + timedelta(hours=1))  # a repeat adds no second proposal
        assert len(os_events(world, plan_id, "playbook_newer")) == 1 and len(pending_proposals(world, plan_id)) == 1
        assert s.steps() == {**before} or set(s.steps()) == set(before)  # the plan itself is unchanged
        # accepted: pinned to version 2, the manual certificates step gives way to the two requests
        world.replanner.accept(s.id, proposal.id)
        assert world.replanner.proposals.get(proposal.id).status == "accepted" and pinned(world, plan_id) == 2
        after = s.steps()
        assert sorted(k for k in after if k.startswith("provide@")) == [f"provide@document:{HSSC}:shown",
                                                                        f"provide@document:{SSC}:shown"]
        assert "school_certificates" not in after
        assert {r.need_ref for r in s.rows("open")} == {SSC, HSSC}
        assert [r["need"]["ref"] for r in s.requests("open")] == sorted([SSC, HSSC])
        s.throughout()


# --- gate off: the app is today's, byte for byte --------------------------------------------------------------------------


def masked_view(s) -> dict:
    """The roadmap's chosen route and the OS inbox, with the ids and the clock-bound stamps masked, so two students compare."""
    import json
    import re

    ids = re.compile(r'"(id|task_id|plan_id|decision_id|student_ref|workspace_id|possibility_id)": ("[^"]*"|\d+)')
    stamp = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})?")
    road, inbox = chosen(s.client, s.params), s.inbox()
    text = json.dumps({"roadmap": road, "inbox": inbox}, sort_keys=True, default=str)
    return json.loads(stamp.sub("<time>", ids.sub(r'"\1": "<id>"', text)))


def test_gate_off_the_plan_view_the_inbox_and_the_roadmap_are_todays(world):
    """The standalone Counsellor and every flag off: version 1, no request row, no `needs`, `GET /v1/os/requests` is a 404, and
    the inbox and the roadmap are what they are on a deployment that has no version 2 at all (the T5 flow's answers)."""
    pre_t8 = {k: v for k, v in world.books.items() if k[1] == 1 or k[0] == "germany_master" and k[1] == 1}
    seen = []
    for books in (None, pre_t8):  # the books of this deployment (v1 and v2), then the books of a deployment before T8
        if books is not None:
            world.svc.plans.playbooks.clear()
            world.svc.plans.playbooks.update(books)
        with signed_in(world, germany_student()) as s, level("master"):
            plan_id = germany_with_the_gate_off(world, s)
            assert pinned(world, plan_id) == 1
            view = s.view()
            assert view["requests"] == [] and all(x["needs"] == [] for x in view["steps"])
            assert s.rows() == [] and not [k for k in s.steps() if k.startswith(("provide@", "which_is_right@", "result_expected@"))]
            assert all("request" not in x for x in chosen(s.client, s.params)["steps"])
            # with every connect flag off the host answers none of the new routes either
            with patch.object(config, "CONNECT_STUDENT_FACTS", False), patch.object(config, "CONNECT_HANDOFF", False):
                assert s.os.get("/v1/os/requests", headers=s.me).status_code == 404
                assert s.os.post("/v1/os/requests/1/answer", json={"ref": "x", "seen": "y", "choice": "current"},
                                 headers=s.me).status_code == 404
            seen.append(masked_view(s))
            s.throughout()
    assert seen[0] == seen[1]  # byte for byte (ids and times masked)
