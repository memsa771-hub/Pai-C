"""P1-T7 Task 4 (R-16, R-01, row 6.7): a document's fields compared live with the Vault, the per-field profile rule,
and the documents the plan needs. Fictional data. Postgres. No model."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.os import models, ports
from app.os.adapters.counsellor import manifest
from app.models import MemoryCandidate
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.contracts.student_facts import StudentFactsV1
from app.os.documents import connect_texts
from app.os.documents.store import DocumentStore, ProfileStore
from app.os.documents.vault_check import compare
from app.os.eligibility.notes import profile_of
from app.os.playbooks import load_playbook_dir
from app.os.ports import document_files, student_facts
from app.os.settings import load_settings
from tests.os.test_api import TEST_TERMS, TOKEN
from tests.os.test_api_documents import TYPES, FakeClient, confirm_body, simulate_read

pytestmark = pytest.mark.req("R-16")

FAKE = Path(__file__).parent / "playbooks"
TENANT = "pai"
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)
ME = {"X-Test-Student": "stu-1"}
TRANSCRIPT = {"student_name": "Sara Ahmed Khan", "father_name": "Ahmed Khan", "date_of_birth": "2001-04-12",
              "institution": "Example University", "cgpa": 3.7, "cgpa_scale": 4.0}


def facts_v1(student="stu-1", **by_key) -> dict:
    """`by_key`: fact key with dots as double underscores -> value, or (value, evidence)."""
    items = []
    for key, v in by_key.items():
        value, evidence = v if isinstance(v, tuple) else (v, "stated")
        items.append({"key": key.replace("__", "."), "value": None if evidence == "unknown" else value,
                      "evidence": evidence, "vault_version": 1})
    return StudentFactsV1.model_validate({"schema": "pai.student_facts.v1", "student_ref": student, "vault_version": 1,
                                          "built_at": NOW, "eligible_levels": None, "facts": items}
                                         ).model_dump(by_alias=True)


@pytest.fixture(autouse=True)
def reset_ports():
    document_files.configure()
    student_facts.configure(None)
    yield
    document_files.configure()
    student_facts.configure(None)
    ports.configure(None)


@pytest.fixture
def api(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ADMIN_TOKEN": TOKEN, "OS_ENABLED": "true"})
    svc = make_services(settings, engine=engine, playbooks=load_playbook_dir(FAKE), dbos_client=lambda: FakeClient(),
                        terms_dir=TEST_TERMS)
    ports.configure(svc)
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix="/v1/os")

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.engine = engine
    return c


def connect(engine, facts: dict | None, on: bool = True):
    """The host part on, the `counsellor` module on, and a StudentFacts adapter answering `facts`."""
    document_files.configure(enabled=lambda: on)
    manifest.set_enabled(engine, TENANT, True)
    student_facts.configure(lambda ref: facts)


def doc(engine, doc_type="transcript", values=TRANSCRIPT, student="stu-1", confirmed=False, n=1) -> int:
    store = DocumentStore(engine, TENANT)
    doc_id = store.create(student, doc_type, TYPES[doc_type].version, f"d{n}.pdf", "application/pdf",
                          b"%PDF-1.4 " + bytes([n]) * 20)
    simulate_read(engine, doc_id, doc_type, values)
    if confirmed:
        store.confirm(doc_id, {f.name: values.get(f.name) for f in TYPES[doc_type].fields})
    return doc_id


def by_field(got: dict) -> dict:
    return {f["field"]: f["outcome"] for f in got["fields"]}


# --- the pure compare -------------------------------------------------------------------------------------------


def facts_obj(**by_key) -> StudentFactsV1:
    return StudentFactsV1.model_validate(facts_v1(**by_key))


def test_vault_check_outcomes():
    t = TYPES["transcript"]
    values = {"student_name": "Sara", "cgpa": 700, "cgpa_scale": "4.0", "percentage": 70}
    got = {f["field"]: f["outcome"] for f in compare(t, values, facts_obj(
        education__bachelor__gpa="700.0", education__bachelor__gpa_scale=5.0,
        education__bachelor__percentage=(None, "unknown")))}
    assert got["cgpa"] == "same"  # 700 and "700.0" are the same number
    assert got["cgpa_scale"] == "differs"  # "4.0" against 5.0
    assert got["percentage"] == "new"  # the Vault does not know it
    assert got["student_name"] == "not_compared"  # no `fact:` key
    other = {f["field"]: f["outcome"] for f in compare(
        t, {"cgpa": 705, "cgpa_scale": 5}, facts_obj(education__bachelor__gpa=700, education__bachelor__gpa_scale=5))}
    assert other["cgpa"] == "differs"  # 700 against 705


def test_a_value_is_comparable_only_with_its_scale_on_both_sides():
    t = TYPES["transcript"]
    out = lambda values, **vault: {f["field"]: f["outcome"] for f in compare(t, values, facts_obj(**vault))}  # noqa: E731
    both = out({"cgpa": 3.5, "cgpa_scale": 5}, education__bachelor__gpa=3.5, education__bachelor__gpa_scale=5)
    assert both["cgpa"] == "same" and both["cgpa_scale"] == "same"
    assert out({"cgpa": 3.5}, education__bachelor__gpa=3.5, education__bachelor__gpa_scale=5)["cgpa"] == "not_compared"
    assert out({"cgpa": 3.5, "cgpa_scale": 5}, education__bachelor__gpa=3.0)["cgpa"] == "not_compared"  # no Vault scale
    h = TYPES["hssc_certificate"]
    got = {f["field"]: f["outcome"] for f in compare(h, {"marks_obtained": 900}, facts_obj(
        education__intermediate__marks_obtained=900, education__intermediate__marks_total=1100))}
    assert got["marks_obtained"] == "not_compared"


def test_compare_text_and_numbers():
    t = TYPES["ielts_trf"]
    f = next(x for x in t.fields if x.fact)
    one = lambda v, vault: next(o["outcome"] for o in compare(t, {f.name: v}, facts_obj(**{f.fact.replace(".", "__"): vault}))
                                if o["field"] == f.name)  # noqa: E731
    assert one(6.5, 6.5) == "same" and one(6.5, 7) == "differs"
    assert one(6.5, "6.5000000001") == "same" and one(6.5, "6.51") == "differs"
    assert one(None, 6.5) == "not_compared"  # nothing to compare


def test_compare_text_is_case_and_space_folded():
    from app.os.documents.types import DocumentType, FieldSpec

    t = DocumentType(key="x_doc", version=1, label="X", fields=[
        FieldSpec(name="level", type="text", hint="h", fact="education.bachelor.degree_level")])
    got = lambda v, vault: compare(t, {"level": v}, facts_obj(education__bachelor__degree_level=vault))[0]["outcome"]  # noqa: E731
    assert got("  Bachelor  of   Arts ", "bachelor of arts") == "same"
    assert got("Bachelor of Arts", "Master of Arts") == "differs"


def test_vault_check_endpoint_outcomes_and_note(api):
    connect(api.engine, facts_v1(education__bachelor__gpa=3.7, education__bachelor__gpa_scale=5.0))
    d = doc(api.engine, confirmed=True)
    got = api.get(f"/v1/os/documents/{d}/vault-check", headers=ME)
    assert got.status_code == 200, got.text
    body = got.json()
    got_by = by_field(body)
    assert [f["field"] for f in body["fields"]] == [f.name for f in TYPES["transcript"].fields]
    assert (got_by["cgpa"], got_by["cgpa_scale"], got_by["student_name"]) == ("same", "differs", "not_compared")
    assert got_by["percentage"] == "not_compared"  # the document has no value for it
    assert body["note"] == connect_texts.text("vault_differs")


def test_note_is_set_only_when_something_differs(api):
    connect(api.engine, facts_v1(education__bachelor__gpa=3.7, education__bachelor__gpa_scale=(None, "unknown")))
    d = doc(api.engine, confirmed=True)
    body = api.get(f"/v1/os/documents/{d}/vault-check", headers=ME).json()
    assert by_field(body)["cgpa"] == "not_compared" and by_field(body)["cgpa_scale"] == "new" and body["note"] is None


def test_unconfirmed_document_compares_the_read_value(api):
    connect(api.engine, facts_v1(education__bachelor__gpa=3.0, education__bachelor__gpa_scale=4.0))
    d = doc(api.engine)  # read, not confirmed: value_read 3.7
    assert by_field(api.get(f"/v1/os/documents/{d}/vault-check", headers=ME).json())["cgpa"] == "differs"


def test_vault_check_404_without_host_or_other_student(api):
    d = doc(api.engine, confirmed=True)
    url = f"/v1/os/documents/{d}/vault-check"
    assert api.get(url, headers=ME).status_code == 404  # no port, no adapter
    connect(api.engine, facts_v1(education__bachelor__gpa=3.7), on=False)
    assert api.get(url, headers=ME).status_code == 404  # the documents port is off
    connect(api.engine, None)
    assert api.get(url, headers=ME).status_code == 404  # the host adapter does not answer: no standalone fallback
    connect(api.engine, facts_v1(education__bachelor__gpa=3.7))
    assert api.get(url, headers=ME).status_code == 200
    assert api.get(url, headers={"X-Test-Student": "stu-2"}).status_code == 404  # another student's document
    assert api.get("/v1/os/documents/99999/vault-check", headers=ME).status_code == 404


def test_vault_check_stores_nothing(api):
    connect(api.engine, facts_v1(education__bachelor__gpa=9.9))
    d = doc(api.engine, confirmed=True)

    def counts():
        with api.engine.connect() as conn:
            return {t.name: conn.execute(select(func.count()).select_from(t)).scalar()
                    for t in models.md.sorted_tables}

    before = counts()
    assert api.get(f"/v1/os/documents/{d}/vault-check", headers=ME).status_code == 200
    assert counts() == before


# --- the per-field rule (D-y12) ---------------------------------------------------------------------------------


def plans_of(engine):
    import types as pytypes

    return pytypes.SimpleNamespace(engine=engine, kernel=pytypes.SimpleNamespace(tenant_id=TENANT))


def own(engine, **values):
    store = ProfileStore(engine, TENANT)
    for key, v in values.items():
        store.set("stu-1", key.replace("__", "."), v, None, source="entered")


def test_per_field_rule_with_both_parts_on(engine, clean):
    ports.configure(None)
    own(engine, transcript__cgpa=3.0, transcript__percentage=61.5, min_passing_grade_letter__min_pass="C",
        min_passing_grade_letter__scale_best="A", entry_test__score=80)
    connect(engine, facts_v1(test__ielts__score=7.0, education__bachelor__percentage=(None, "unknown")))
    got = profile_of(plans_of(engine), "stu-1")
    assert "transcript.cgpa" not in got and "transcript.percentage" not in got  # a `fact:` field: only the Vault
    assert got["ielts_trf.overall"] == 7.0
    assert got["min_passing_grade_letter.min_pass"] == "C"  # no Vault type: still the stored value
    assert got["min_passing_grade_letter.scale_best"] == "A"
    assert got["entry_test.score"] == 80


def test_per_field_rule_mixes_nothing_from_a_half_known_type(engine, clean):
    own(engine, transcript__cgpa=3.9, transcript__cgpa_scale=5.0, transcript__percentage=40)
    connect(engine, facts_v1(education__bachelor__gpa=3.2))
    assert profile_of(plans_of(engine), "stu-1") == {"transcript.cgpa": 3.2}


def test_per_field_rule_keeps_cross_check_values(engine, clean):
    own(engine, full_name="Sara Ahmed Khan", transcript__cgpa=3.9)
    connect(engine, facts_v1(test__ielts__score=7.0))
    got = profile_of(plans_of(engine), "stu-1")
    assert got == {"full_name": "Sara Ahmed Khan", "ielts_trf.overall": 7.0}


def test_only_the_student_facts_part_keeps_the_per_type_overlay(engine, clean):
    own(engine, transcript__cgpa=3.0, hssc_certificate__marks_obtained=700)
    connect(engine, facts_v1(education__intermediate__marks_total=1100), on=False)  # the documents port is off
    got = profile_of(plans_of(engine), "stu-1")
    assert got == {"transcript.cgpa": 3.0, "hssc_certificate.marks_total": 1100}  # today's T4 overlay, per type


# --- the same verdict through the Vault (row 6.7) ---------------------------------------------------------------

from tests.os.test_fact_proposals import world  # noqa: E402,F401  (the real bridge on a student session)


def test_germany_eligibility_same_after_confirm_and_reconcile(world):
    """A confirmed transcript reaches the Vault as `education.bachelor.gpa`; the evaluator then gives the same verdict
    from StudentFacts as from the T4 document profile (os_profile_values)."""
    from app import pai_os_bridge as bridge
    from app.memory.reconciler import MemoryReconciler
    from app.os.eligibility.evaluate import evaluate
    from app.os.eligibility.facts import current_types, profile_from_facts
    from app.os.knowledge.port import Fact
    from app.os.playbooks import PLAYBOOK_DIR
    from app.pai_c.connect import student_facts as builder
    from tests.os.test_student_facts_port import CASES

    values = {**TRANSCRIPT, "cgpa": 3.2, "cgpa_scale": 4.0, "percentage": None}
    doc_id = world.typed("transcript", name="t.pdf")
    world.read(doc_id, "transcript", values)
    world.confirm(doc_id, "transcript", values)
    with world.who.factory() as db:
        bridge.deliver_fact_proposals(db)
        for candidate in db.scalars(select(MemoryCandidate)).all():
            assert MemoryReconciler(db).reconcile(candidate).accepted
        db.commit()
        facts = builder.build(db, world.id)
    assert {f["key"]: f["value"] for f in facts["facts"]}["education.bachelor.gpa"] == 3.2
    from_vault = profile_from_facts(StudentFactsV1.model_validate(facts), current_types())
    from_documents = {v["key"]: v["value"] for v in ProfileStore(world.svc.engine, TENANT).all(world.id)
                      if v["key"].startswith("transcript.")}
    assert from_vault["transcript.cgpa"] == from_documents["transcript.cgpa"] == 3.2
    book, research = CASES["germany"][0], CASES["germany"][1]
    rules = load_playbook_dir(PLAYBOOK_DIR)[(book, 1)].eligibility
    assert evaluate(rules, "p", research, from_vault) == evaluate(rules, "p", research, from_documents)
