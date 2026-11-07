"""P1-T8 Task 4 (R-21, R-19): a Vault conflict becomes a "which is right" step, the answer goes to the Vault from the OS
and from the Vault page, and the step and request close in one change. The Counsellor side is the real Vault and HTTP API
on a student session (SQLite); the OS side is the real services on Postgres behind the real bridge functions. Fictional
student and marks. No model call."""

import types as pytypes
from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import pai_os_bridge as bridge
from app.config import config
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.models import MemoryCandidate, OsOutbox, ProfileIssue
from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.contracts.route_contract import RouteContract
from app.os.documents.store import DocumentStore, FindingStore
from app.os.knowledge import Fact, SqlKnowledge
from app.os.requests import store as request_store
from app.os.requests.refresh import refresh
from app.os.settings import load_settings
from app.pai_c.connect import document_facts
from tests.one_upload_support import upload_world
from tests.os.test_api import TEST_TERMS, TOKEN
from tests.os.test_api_documents import FakeClient, jpeg
from tests.os.test_compile_needs import BOOKS
from tests.test_document_facts import add_file, education, proposal, reconcile_all, stated

pytestmark = pytest.mark.req("R-21")

TENANT, TODAY = "pai", date(2027, 3, 1)
OBTAINED, TOTAL = "education.intermediate.marks_obtained", "education.intermediate.marks_total"
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
WHICH = f"which_is_right@fact:{OBTAINED}:stated"
PROVIDE = f"provide@fact:{OBTAINED}:stated"


def contract(student, level="bachelor", refs=("p1",)) -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"self:{student}", "student_ref": student,
        "origin_country": "PK", "destination_country": "PK", "level": level,
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


class World:
    def __init__(self, svc, engine, who, client, os_client, auth, inflate):
        self.svc, self.engine, self.who, self.client, self.api, self.auth = svc, engine, who, client, os_client, auth
        self.ws, self.inflate = who.workspace_id, inflate
        self.head = {"x-test-student": who.workspace_id}

    # --- the Vault ---
    def saved(self, db, obtained=800, total=1100):
        return stated(db, self.ws, "FSc", institution_name="A College",
                      result={"marks_obtained": obtained, "marks_total": total})

    def hssc_says(self, db, value, key="fact_proposal:7:1"):
        """A confirmed intermediate certificate reads `value`: the Vault opens a card when it differs from what is saved."""
        outcome, ids = document_facts.apply(db, proposal(self.who, add_file(db, self.ws), [
            {"key": OBTAINED, "value": value}], key=key, doc_type="hssc_certificate"))
        db.commit()
        assert outcome == "written"
        return reconcile_all(db, ids)

    def card(self, db) -> ProfileIssue:
        db.expire_all()
        return db.scalars(select(ProfileIssue).order_by(ProfileIssue.created_at)).first()

    # --- the OS ---
    def start(self, level="bachelor") -> int:
        return self.svc.plans.start_plan(contract(self.ws, level)).plan_id

    def requests(self) -> list[dict]:
        got = self.api.get("/v1/os/requests", headers=self.head)
        assert got.status_code == 200, got.text
        return got.json()["requests"]

    def asking(self, kind="which_is_right") -> dict:
        (found,) = [r for r in self.requests() if r["kind"] == kind and r["status"] == "open"]
        return found

    def seen_of(self, request_id) -> tuple[str, str]:
        """The question and the values the student sees for a request now (what the client sends back)."""
        got = self.api.get("/v1/os/requests", headers=self.head)
        found = [r for r in got.json()["requests"] if r["id"] == request_id] if got.status_code == 200 else []
        return ((found[0]["ref"] or "none"), (found[0]["seen"] or "none")) if found else ("none", "none")

    def answer(self, request_id, choice, value=None, student=None, ref=None, seen=None):
        shown_ref, shown_seen = self.seen_of(request_id)
        body = {"ref": ref or shown_ref, "seen": seen or shown_seen, "choice": choice,
                **({"value": value} if value is not None else {})}
        return self.api.post(f"/v1/os/requests/{request_id}/answer", json=body,
                             headers={"x-test-student": student or self.ws})

    def steps(self, plan_id) -> dict[str, str]:
        with self.engine.connect() as conn:
            return {r.instance_key: r.state for r in conn.execute(select(models.tasks).where(
                models.tasks.c.plan_id == plan_id))}

    def row(self, request_id):
        return request_store.get(self.engine, TENANT, request_id)


@pytest.fixture
def books():
    return BOOKS


@pytest.fixture
def world(engine, clean, os_db, tmp_path, monkeypatch, books):
    fake = FakeClient()
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: TODAY, dbos_client=lambda: fake,
                        terms_dir=TEST_TERMS)
    SqlKnowledge(engine, TENANT).upsert("programme", "p1", "merit_list_date", Fact(
        {"date": "2027-08-15"}, "q", "https://uni.example/x", CHECKED, 2027, "confirmed"), "manual")
    manifest.set_enabled(engine, TENANT, True)
    inflate = {"on": False}

    def facts(ref):
        """The real StudentFacts; with `inflate` on, a mark above its total (the Vault itself refuses such a record)."""
        built = bridge.student_facts(ref)
        if built and inflate["on"]:
            for f in built["facts"]:
                if f["key"] == OBTAINED and f["value"] == 800:
                    f["value"] = 2000
        return built

    ports.configure(svc, student_facts=facts, fact_conflicts=bridge.fact_conflicts,
                    fact_answer=bridge.answer_fact_question)
    monkeypatch.setattr(config, "CONNECT_STUDENT_FACTS", True)
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    try:
        with upload_world(tmp_path) as (client, who, auth):
            yield World(svc, engine, who, client, TestClient(app), auth, inflate)
    finally:
        ports.configure(None)


@pytest.fixture
def conflict(world):
    """A saved mark of 800 (said by the student), a plan, then a certificate that reads 760: the question is asked."""
    with world.who.factory() as db:
        world.saved(db)
    plan_id = world.start()
    with world.who.factory() as db:
        world.hssc_says(db, 760)  # the certificate is read after the plan was made
    assert refresh(world.svc, world.ws, "test") == 1  # the hourly recompile notices a card that opened
    return pytypes.SimpleNamespace(plan_id=plan_id, asked=world.asking())


# --- what the student sees ------------------------------------------------------------------------------------------

def test_the_conflict_becomes_a_which_is_right_step_that_pauses_what_uses_it(world, conflict):
    steps = world.steps(conflict.plan_id)
    assert steps[WHICH] == "waiting_student" and PROVIDE not in steps  # one request per fact: the question, not the ask
    assert steps["entry_test"] == "blocked"
    assert conflict.asked["need"] == {"kind": "fact", "ref": OBTAINED, "evidence": "stated"}


def test_get_requests_shows_both_values_and_sources_live(world, conflict):
    a = conflict.asked
    assert a["allow_new"] is True and a["new_label"] and a["how"]
    current, proposed = a["choices"]
    with world.who.factory() as db:
        assert a["ref"] == f"profile_issue:{world.card(db).id}"
    assert [(c["ref"], c["key"]) for c in a["choices"]] == [(a["ref"], OBTAINED)] * 2  # M2: what the student saw
    with world.who.factory() as db:
        file_id = db.get(MemoryCandidate, world.card(db).candidate_id).evidence["file_id"]
    assert (current["choice"], current["value"], current["label"]) == ("current", 800, "Saved in PAI")
    assert current["source"]["kind"] == "vault" and current["source"]["evidence"] == "stated"  # not "chat": unknown
    assert current["source"]["document_ref"] is None and current["source"]["as_of"]
    assert (proposed["choice"], proposed["value"], proposed["label"]) == ("proposed", 760, "From your document")
    assert proposed["source"]["kind"] == "document" and proposed["source"]["evidence"] == "shown"
    assert proposed["source"]["document_ref"] == file_id and proposed["source"]["as_of"]
    # live: the student corrects the saved value on their profile page while the card is open; the next read shows it
    with world.who.factory() as db:
        edit = MemoryCandidateService(db).propose(
            world.ws, "student_record", key="education", proposed_value={"result": {"marks_obtained": 805}},
            confidence=1.0, source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            entities={"record_id": education(db, world.ws)[0]["id"]}, evidence={"quote": "q", "capture": "details"})
        assert MemoryReconciler(db).reconcile(edit).accepted
        db.commit()
    assert world.asking()["choices"][0]["value"] == 805
    with world.engine.connect() as conn:  # nothing of it is stored in the OS (R-01)
        stored = conn.execute(select(models.student_requests)).all()
    assert all(805 not in tuple(r) and 760 not in tuple(r) and 800 not in tuple(r) for r in stored)


# --- the answer ----------------------------------------------------------------------------------------------------

def last_written(db):
    """The newest candidate an OS answer wrote."""
    return db.scalars(select(MemoryCandidate).where(MemoryCandidate.input_channel == "profile")
                      .order_by(MemoryCandidate.created_at.desc())).first()


def assert_closed(world, plan_id, asked):
    row = world.row(asked["id"])
    assert row.status == "answered" and row.closed_cause == "request_answered"
    done = [k for k, s in world.steps(plan_id).items() if k.startswith(WHICH) and s == "done"]
    assert len(done) == 1  # renamed on close, so the same question can be asked again


def test_answer_proposed_resolves_the_card_and_closes_the_step(world, conflict):
    got = world.answer(conflict.asked["id"], "proposed")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    with world.who.factory() as db:
        (row,) = education(db, world.ws)
        assert row["result"]["marks_obtained"] == 760 and row["evidence_level"] == "stated"
        card = world.card(db)
        assert card.status == "resolved" and card.resolution["action"] == "answered_by_value"
        candidate = last_written(db)
        assert candidate.source_type == "user_explicit" and candidate.evidence["capture"] == "os_which_is_right"
        assert candidate.evidence["os_request_id"] == conflict.asked["id"] and candidate.evidence["quote"]  # M4
        assert candidate.proposed_value["value"] == {"result": {"marks_obtained": 760}}
    assert_closed(world, conflict.plan_id, conflict.asked)
    assert world.steps(conflict.plan_id)["entry_test"] == "waiting_student"  # the step that was paused is the student's again
    assert [r for r in world.requests() if r["kind"] == "which_is_right"][0]["status"] == "answered"


def test_answer_current_keeps_the_vault_value_and_closes_the_step(world, conflict):
    with world.who.factory() as db:
        before = db.scalar(select(func.count()).select_from(MemoryCandidate))
    got = world.answer(conflict.asked["id"], "current")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    with world.who.factory() as db:
        assert education(db, world.ws)[0]["result"]["marks_obtained"] == 800
        assert world.card(db).resolution["answers"] == {OBTAINED: {
            "choice": "current", "field": "marks_obtained", "value": 800, "request_id": conflict.asked["id"]}}
        assert db.scalar(select(func.count()).select_from(MemoryCandidate)) == before  # nothing was written
    assert_closed(world, conflict.plan_id, conflict.asked)


def test_answer_new_writes_the_typed_value(world, conflict):
    got = world.answer(conflict.asked["id"], "new", "770")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    with world.who.factory() as db:
        (row,) = education(db, world.ws)
        assert row["result"] == {"marks_obtained": 770, "marks_total": 1100}
        assert world.card(db).resolution["answers"][OBTAINED]["choice"] == "new"
    assert_closed(world, conflict.plan_id, conflict.asked)


def test_a_refused_answer_writes_nothing_and_keeps_the_step(world, conflict):
    for body in (("new", None), ("new", "abc"), ("new", "9999")):
        got = world.answer(conflict.asked["id"], *body)
        assert got.status_code == 422, got.text
    with world.who.factory() as db:
        assert world.card(db).status == "open" and education(db, world.ws)[0]["result"]["marks_obtained"] == 800
    assert world.row(conflict.asked["id"]).status == "open"
    ref, seen = conflict.asked["ref"], conflict.asked["seen"]
    for body in ({"ref": ref, "seen": seen, "choice": "maybe"}, {"ref": ref, "seen": seen, "choice": "new", "x": 1},
                 {"choice": "current"}, {"ref": ref, "choice": "current"}):
        assert world.api.post(f"/v1/os/requests/{conflict.asked['id']}/answer", json=body,
                              headers=world.head).status_code == 422  # a body without `ref` is refused too


def test_impossible_value_answer_writes_through_the_reconciler(world):
    with world.who.factory() as db:
        world.saved(db)
    world.inflate["on"] = True  # the Vault holds 800; the facts the OS reads say 2000 of 1100
    plan_id = world.start()
    asked = world.asking()
    assert asked["kind"] == "which_is_right" and asked["choices"] == [] and asked["allow_new"] is True
    from app.os.requests import texts

    assert asked["how"] == texts.text("how_impossible")
    assert world.answer(asked["id"], "current").status_code == 422  # only a new value is taken
    got = world.answer(asked["id"], "new", "760")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    with world.who.factory() as db:
        (row,) = education(db, world.ws)
        assert row["result"]["marks_obtained"] == 760 and row["evidence_level"] == "stated"
        candidate = db.scalars(select(MemoryCandidate).order_by(MemoryCandidate.created_at.desc())).first()
        assert candidate.evidence["capture"] == "os_which_is_right" and candidate.source_type == "user_explicit"
        assert candidate.evidence["os_request_id"] == asked["id"] and candidate.evidence["quote"]  # M4: impossible path
    assert world.row(asked["id"]).status == "answered"
    assert not [k for k, s in world.steps(plan_id).items() if k.startswith("which_is_right@") and s != "done"]


def test_answer_twice_is_already_answered(world, conflict):
    assert world.answer(conflict.asked["id"], "proposed").status_code == 200
    again = world.answer(conflict.asked["id"], "proposed")
    assert again.status_code == 409 and again.json()["detail"] == "already_answered"


def test_answer_for_a_closed_card_is_gone_and_closes(world, conflict):
    """The card was answered on the Vault page a moment ago (the OS has not heard yet): the answer is not an error."""
    from app.memory.profile_issues import ProfileIssueService

    with world.who.factory() as db:
        ProfileIssueService(db).resolve(world.ws, world.card(db).id, "keep_current")
        db.commit()
    assert world.row(conflict.asked["id"]).status == "open"  # not heard yet
    got = world.answer(conflict.asked["id"], "proposed")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    with world.who.factory() as db:
        assert education(db, world.ws)[0]["result"]["marks_obtained"] == 800  # the Vault page's answer stands
    assert world.row(conflict.asked["id"]).status == "answered"


def test_a_request_that_asks_for_information_is_answered_by_giving_it(world):
    world.start()
    ask = next(r for r in world.requests() if r["kind"] == "provide")
    got = world.answer(ask["id"], "new", "800")
    assert got.status_code == 409 and got.json()["detail"] == "answer_elsewhere"


def test_answer_404_for_another_student_or_tenant(world, conflict):
    other = world.answer(conflict.asked["id"], "proposed", student="someone-else")
    assert other.status_code == 404
    assert world.answer(999999, "proposed").status_code == 404
    with world.engine.begin() as conn:  # a row of another tenant is not found either
        conn.execute(models.student_requests.update().where(models.student_requests.c.id == conflict.asked["id"])
                     .values(tenant_id="other-tenant"))
    assert world.answer(conflict.asked["id"], "proposed").status_code == 404
    with world.who.factory() as db:
        assert world.card(db).status == "open"


def test_answer_404_while_part_off(world, conflict, monkeypatch):
    monkeypatch.setattr(config, "CONNECT_STUDENT_FACTS", False)  # the gate: the host answers None
    got = world.answer(conflict.asked["id"], "proposed")
    assert got.status_code == 404 and got.json() == {"detail": "Not Found"}
    assert world.api.get("/v1/os/requests", headers=world.head).status_code == 404
    with world.who.factory() as db:
        assert world.card(db).status == "open"
    monkeypatch.setattr(config, "CONNECT_STUDENT_FACTS", True)
    # the OS gate is on but the host's own answer part is off (the module switch): the callback answers None
    with patch.object(bridge, "part_on", return_value=False):
        assert world.answer(conflict.asked["id"], "proposed").status_code == 404
    with world.who.factory() as db:
        assert world.card(db).status == "open" and education(db, world.ws)[0]["result"]["marks_obtained"] == 800


# --- answered anywhere closes it everywhere (R-19) -----------------------------------------------------------------

@pytest.mark.req("R-19")
def test_vault_page_keep_current_reaches_the_os(world, conflict):
    """The student answers on the Vault page. Nothing is written (keep current), so the reconciler's hook does not fire;
    the close hook bumps the version, a vault_event leaves, the OS recompiles and the step is done."""
    with world.who.factory() as db:
        card_id = world.card(db).id
        before = db.scalar(select(func.count()).select_from(OsOutbox).where(OsOutbox.kind == "vault_event"))
    got = world.client.post(f"/v1/vault/conflicts/{card_id}/resolve?network={world.ws}", headers=world.auth,
                            json={"answer": "keep_current"})
    assert got.status_code == 200, got.text
    assert world.row(conflict.asked["id"]).status == "open"  # not heard yet
    with world.who.factory() as db:
        events = db.scalars(select(OsOutbox).where(OsOutbox.kind == "vault_event")).all()
        assert len(events) == before + 1
        assert OBTAINED in max(events, key=lambda r: r.payload["vault_version"]).payload["keys"]
        assert bridge.deliver_pending(db, world.ws)["failed"] == 0
    row = world.row(conflict.asked["id"])
    assert row.status == "answered" and row.closed_cause == "request_answered"
    assert [k for k, s in world.steps(conflict.plan_id).items() if k.startswith(WHICH) and s == "done"]
    assert world.steps(conflict.plan_id)["entry_test"] == "waiting_student"


@pytest.mark.req("R-19")
def test_vault_page_accept_proposed_reaches_the_os(world, conflict):
    with world.who.factory() as db:
        card_id = world.card(db).id
    got = world.client.post(f"/v1/vault/conflicts/{card_id}/resolve?network={world.ws}", headers=world.auth,
                            json={"answer": "accept_proposed"})
    assert got.status_code == 200, got.text
    with world.who.factory() as db:
        assert bridge.deliver_pending(db, world.ws)["failed"] == 0
    assert world.row(conflict.asked["id"]).status == "answered"


# --- two documents that differ stay in the OS (Ruling problems 4) --------------------------------------------------

def test_finding_answer_uses_resolve_finding_and_never_the_vault(world):
    store = DocumentStore(world.engine, TENANT)
    a = store.create(world.ws, "hssc_certificate", 1, "a.jpg", "image/jpeg", jpeg(1))
    b = store.create(world.ws, "ssc_certificate", 1, "b.jpg", "image/jpeg", jpeg(2))
    FindingStore(world.engine, TENANT).replace_open(world.ws, [{"kind": "mismatch", "field": "father_name",
                                                                "items": [(a, "Ahmed Khan"), (b, "Rashid Khan")]}])
    plan_id = world.start()
    asked = [r for r in world.requests() if r["kind"] == "which_is_right"]
    (one,) = asked  # the route needs the intermediate certificate only; the other paper is not asked about
    assert one["need"] == {"kind": "document", "ref": "hssc_certificate", "evidence": "shown"}
    assert [(c["choice"], c["value"], c["source"]["kind"]) for c in one["choices"]] == [
        (f"doc:{a}", "Ahmed Khan", "document"), (f"doc:{b}", "Rashid Khan", "document")]  # each document its own id
    assert {c["ref"] for c in one["choices"]} == {one["ref"]} and one["ref"].startswith("finding:")
    assert one["allow_new"] is False
    # review M7: a value that is none of the documents' on an OPEN finding is refused with exactly 422, and nothing is closed
    assert world.answer(one["id"], "new", "Someone Else").status_code == 422
    assert FindingStore(world.engine, TENANT).list_open(world.ws) != []
    assert world.answer(one["id"], "current").status_code == 422  # the old ids are not choices of a finding
    assert world.answer(one["id"], "new", "Ahmed Khan").status_code == 422  # review M-3: even a listed value
    with world.who.factory() as db:
        before = (db.scalar(select(func.count()).select_from(MemoryCandidate)),
                  db.scalar(select(func.count()).select_from(OsOutbox)))
    got = world.answer(one["id"], f"doc:{b}")
    assert got.status_code == 200 and got.json() == {"status": "answered"}
    assert FindingStore(world.engine, TENANT).list_open(world.ws) == []
    from app.os.documents.store import ProfileStore

    (value,) = [v for v in ProfileStore(world.engine, TENANT).all(world.ws) if v["key"] == "father_name"]
    assert value["value"] == "Rashid Khan" and value["source_document_id"] == b
    with world.who.factory() as db:  # the Vault saw nothing
        assert (db.scalar(select(func.count()).select_from(MemoryCandidate)),
                db.scalar(select(func.count()).select_from(OsOutbox))) == before
    assert {r["status"] for r in world.requests() if r["kind"] == "which_is_right"} == {"answered"}
    assert not [k for k, s in world.steps(plan_id).items() if k.startswith("which_is_right@") and s != "done"]
    assert world.answer(one["id"], f"doc:{b}").status_code == 409  # answered


def test_a_finding_with_three_documents_gives_each_its_own_choice(world):
    """Review M6: the third document is a third choice, never labelled "new" while typing a value is not allowed."""
    store = DocumentStore(world.engine, TENANT)
    ids = [store.create(world.ws, t, 1, f"{t}.jpg", "image/jpeg", jpeg(n)) for n, t in zip(
        (1, 80, 160), ("hssc_certificate", "ssc_certificate", "transcript"))]
    values = ["Ahmed Khan", "Rashid Khan", "Rasheed Khan"]
    FindingStore(world.engine, TENANT).replace_open(world.ws, [{"kind": "mismatch", "field": "father_name",
                                                                "items": list(zip(ids, values))}])
    world.start()
    (one,) = [r for r in world.requests() if r["kind"] == "which_is_right"]
    assert [c["choice"] for c in one["choices"]] == [f"doc:{i}" for i in ids] and one["allow_new"] is False
    assert [c["value"] for c in one["choices"]] == values and "new" not in {c["choice"] for c in one["choices"]}
    assert world.answer(one["id"], f"doc:{ids[2]}").status_code == 200
    from app.os.documents.store import ProfileStore

    (value,) = [v for v in ProfileStore(world.engine, TENANT).all(world.ws) if v["key"] == "father_name"]
    assert value["value"] == "Rasheed Khan"


# --- review fixes: an unexpected host error, a changed question, one read of the host ----------------------------------

def test_an_unexpected_host_error_is_503_not_404(world, conflict):
    """Review M1: 404 means "does not exist / part off"; a host that fails is `counsellor_unavailable` (503)."""
    with patch("app.pai_c.connect.fact_conflicts.answer", side_effect=RuntimeError("boom")):
        got = world.answer(conflict.asked["id"], "proposed")
    assert got.status_code == 503 and got.json() == {"detail": "counsellor_unavailable"}
    with world.who.factory() as db:
        assert world.card(db).status == "open" and education(db, world.ws)[0]["result"]["marks_obtained"] == 800
    assert world.row(conflict.asked["id"]).status == "open"
    # the bridge itself returns the distinct status, and names only the class of the error in its log
    with patch("app.pai_c.connect.fact_conflicts.answer", side_effect=RuntimeError("boom")), patch.object(
            bridge, "part_on", return_value=True):
        assert bridge.answer_fact_question(world.ws, "profile_issue:x", OBTAINED, "current") == {"status": "error"}


def test_an_answer_to_a_question_that_changed_is_refused(world, conflict):
    """Review M2: the answer names the question the student saw; another card now → 409 `answer_changed`, nothing written."""
    from app.os.requests import texts

    stale = conflict.asked["ref"]
    with world.who.factory() as db:  # the card closes and a newer certificate opens another one
        from app.memory.profile_issues import ProfileIssueService

        ProfileIssueService(db).resolve(world.ws, world.card(db).id, "keep_current")
        db.commit()
        world.hssc_says(db, 770, key="fact_proposal:8:1")
    assert refresh(world.svc, world.ws, "test") >= 0
    got = world.answer(conflict.asked["id"], "proposed", ref=stale)
    assert got.status_code == 409
    assert got.json() == {"detail": "answer_changed", "note": texts.text("answer_changed")}
    with world.who.factory() as db:
        assert education(db, world.ws)[0]["result"]["marks_obtained"] == 800
        assert db.scalars(select(ProfileIssue).where(ProfileIssue.status == "open")).first() is not None
    fresh = world.answer(conflict.asked["id"], "proposed")  # the ref of what is shown now is taken
    assert fresh.status_code == 200
    with world.who.factory() as db:
        assert education(db, world.ws)[0]["result"]["marks_obtained"] == 770


def test_get_requests_reads_the_host_once(world, conflict):
    """Review M3: no read per request. The host's conflicts are read once for the whole list."""
    calls = []
    real = bridge.fact_conflicts

    def counting(ref):
        calls.append(ref)
        return real(ref)

    ports.configure(world.svc, student_facts=bridge.student_facts, fact_conflicts=counting,
                    fact_answer=bridge.answer_fact_question)
    got = world.api.get("/v1/os/requests", headers=world.head)
    assert got.status_code == 200 and [r for r in got.json()["requests"] if r["kind"] == "which_is_right"]
    assert len(calls) == 1


def test_an_answer_to_values_that_changed_is_refused(world, conflict):
    """Review M-2: the saved value moves from 800 to 805 between the GET and the POST: the answer is refused."""
    shown = conflict.asked
    with world.who.factory() as db:
        edit = MemoryCandidateService(db).propose(
            world.ws, "student_record", key="education", proposed_value={"result": {"marks_obtained": 805}},
            confidence=1.0, source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            entities={"record_id": education(db, world.ws)[0]["id"]}, evidence={"quote": "q", "capture": "details"})
        assert MemoryReconciler(db).reconcile(edit).accepted
        db.commit()
    from app.os.requests import texts

    got = world.answer(shown["id"], "proposed", ref=shown["ref"], seen=shown["seen"])
    assert got.status_code == 409 and got.json() == {"detail": "answer_changed", "note": texts.text("answer_changed")}
    with world.who.factory() as db:
        assert education(db, world.ws)[0]["result"]["marks_obtained"] == 805 and world.card(db).status == "open"
    assert world.asking()["seen"] != shown["seen"]
    assert world.answer(shown["id"], "proposed").status_code == 200  # what is shown now is taken
