"""Slice 9a Task 5: pilot consent (spec §3.2, §4, §5, §7; plan Review Focus 3). Fictional data."""

import io
from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import func, select

from app.os import clock, models
from app.os.consent import CONSENT_DIR, ConsentStore, Terms, current_terms
from tests.os.test_api import TEST_TERMS, agree
from tests.os.test_api_self_serve import P, build_api, me, start
from tests.os.test_invariants import COUNTRY_TERMS

TENANT = "pai"


@pytest.fixture(autouse=True)
def real_clock():
    """Rehearsal mode installs the stored-offset clock; put real time back for the next test."""
    clock.configure(None)
    yield
    clock.configure(None)


def terms_file(folder: Path, version: int, placeholder: bool = False, text: str | None = None) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    body = text if text is not None else f"Pilot terms, version {version}."
    (folder / f"pilot.v{version}.md").write_text(
        f"---\nversion: {version}\nplaceholder: {'true' if placeholder else 'false'}\n---\n{body}\n", encoding="utf-8")


def raw_start(api, student="stu-1"):
    return api.post(f"{P}/plans/self", headers=me(student), json={
        "route": "ireland_master", "intake": {"term": "winter", "year": 2027},
        "choices": [{"programme_ref": "p1", "rank": 1}]})


def raw_upload(api, student="stu-1"):
    out = io.BytesIO()
    Image.new("RGB", (300, 400), (1, 120, 120)).save(out, "JPEG")
    return api.post(f"{P}/documents", data={"doc_type": "transcript"},
                    files={"file": ("transcript.jpg", out.getvalue(), "image/jpeg")}, headers=me(student))


def count(engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar_one()


def code(r) -> str:
    return r.json()["detail"]["code"]


@pytest.fixture
def api(engine, clean, os_db):
    return build_api(engine, os_db)


# --- the refusals --------------------------------------------------------------------------------------------------


def test_start_needs_consent(api, engine):
    r = raw_start(api)
    assert r.status_code == 409 and code(r) == "consent_needed"
    assert count(engine, models.plans) == 0
    # checked before any other work: even a body that would be refused (422) gets the consent refusal first
    bad = api.post(f"{P}/plans/self", headers=me(), json={"route": "mars"})
    assert bad.status_code == 409 and code(bad) == "consent_needed"


def test_upload_needs_consent(api, engine):
    r = raw_upload(api)
    assert r.status_code == 409 and code(r) == "consent_needed"
    assert count(engine, models.documents) == 0 and api.fake.calls == []  # nothing stored, nothing enqueued
    bad = api.post(f"{P}/documents", data={"doc_type": "no_such_type"},
                   files={"file": ("a.jpg", b"x", "image/jpeg")}, headers=me())
    assert bad.status_code == 409 and code(bad) == "consent_needed"


def test_agree_then_start(api, engine):
    got = api.get(f"{P}/consent", headers=me()).json()
    assert got == {"version": 1, "text": got["text"], "placeholder": False, "agreed": False} and got["text"]
    assert api.post(f"{P}/consent", json={"version": 1}, headers=me()).status_code == 204
    assert api.get(f"{P}/consent", headers=me()).json()["agreed"] is True
    assert api.get(f"{P}/consent", headers=me("stu-2")).json()["agreed"] is False  # per student
    assert raw_start(api).status_code == 201
    assert raw_upload(api).status_code == 201
    assert raw_start(api, "stu-2").status_code == 409


def test_agree_twice_is_fine(api, engine):
    assert api.post(f"{P}/consent", json={"version": 1}, headers=me()).status_code == 204
    assert api.post(f"{P}/consent", json={"version": 1}, headers=me()).status_code == 204
    assert count(engine, models.consents) == 1
    with engine.connect() as conn:
        row = conn.execute(select(models.consents)).one()
    assert (row.tenant_id, row.student_ref, row.terms_version) == (TENANT, "stu-1", 1)
    assert row.agreed_at.tzinfo is not None


def test_consent_needs_sign_in(api):
    assert api.get(f"{P}/consent").status_code == 401
    assert api.post(f"{P}/consent", json={"version": 1}).status_code == 401


def test_old_version_refused(engine, clean, os_db, tmp_path):
    terms_file(tmp_path, 1)
    terms_file(tmp_path, 2)
    api = build_api(engine, os_db, terms_dir=tmp_path)
    r = api.post(f"{P}/consent", json={"version": 1}, headers=me())
    assert r.status_code == 409 and code(r) == "consent_version"
    assert api.post(f"{P}/consent", json={"version": 3}, headers=me()).status_code == 409
    assert count(engine, models.consents) == 0
    assert api.post(f"{P}/consent", json={"version": 2}, headers=me()).status_code == 204


def test_placeholder_refused_outside_rehearsal(engine, clean, os_db):
    api = build_api(engine, os_db, terms_dir=None)  # the shipped terms: still a placeholder
    got = api.get(f"{P}/consent", headers=me()).json()
    assert got["placeholder"] is True and got["agreed"] is False
    r = api.post(f"{P}/consent", json={"version": got["version"]}, headers=me())
    assert r.status_code == 409 and code(r) == "terms_not_set"
    assert count(engine, models.consents) == 0
    assert raw_start(api).status_code == 409  # so no real student can start before the owners write the text


def test_placeholder_accepted_in_rehearsal(engine, clean, os_db):
    api = build_api(engine, os_db, terms_dir=None, rehearsal=True)
    version = api.get(f"{P}/consent", headers=me()).json()["version"]
    assert api.post(f"{P}/consent", json={"version": version}, headers=me()).status_code == 204
    assert raw_start(api).status_code == 201


def test_new_terms_version_blocks_start_not_inbox(engine, clean, os_db, tmp_path):
    """Review Focus 3: agreed to v1, then v2 appears: no new plan or upload until they agree again, but the inbox
    and the running plan keep working."""
    terms_file(tmp_path, 1)
    api = build_api(engine, os_db, terms_dir=tmp_path)
    agree(api)
    plan = start(api, refs=("p1",)).json()["plan_id"]
    terms_file(tmp_path, 2)
    assert api.get(f"{P}/consent", headers=me()).json() == {
        "version": 2, "text": "Pilot terms, version 2.", "placeholder": False, "agreed": False}
    r = raw_start(api)
    assert r.status_code == 409 and code(r) == "consent_needed"
    assert code(raw_upload(api)) == "consent_needed"
    inbox = api.get(f"{P}/inbox", headers=me())
    assert inbox.status_code == 200 and inbox.json()["items"]
    swap = api.post(f"{P}/plans/{plan}/swap", headers=me(), json={"out": "p1", "in": "p2"})
    assert swap.status_code == 200  # a change to the running plan is not a new start
    item = api.get(f"{P}/inbox", headers=me()).json()["items"][0]
    assert api.post(f"{P}/inbox/{item['id']}/complete", json={}, headers=me()).status_code == 200
    agree(api)
    again = raw_start(api)  # agreed to v2: past the consent check (the plan now holds p2, so this is the normal 409)
    assert again.status_code == 409 and "already have a plan" in again.json()["detail"]
    assert raw_upload(api).status_code == 201


# --- the terms loader and the store --------------------------------------------------------------------------------


def test_current_terms_picks_highest_version(tmp_path):
    terms_file(tmp_path, 2)
    terms_file(tmp_path, 10, placeholder=True, text="Ten.")
    terms_file(tmp_path, 9)
    (tmp_path / "notes.md").write_text("not terms", encoding="utf-8")
    assert current_terms(tmp_path) == Terms(version=10, text="Ten.", placeholder=True)


def test_terms_file_must_match_its_name(tmp_path):
    (tmp_path / "pilot.v2.md").write_text("---\nversion: 1\nplaceholder: false\n---\nx\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        current_terms(tmp_path)
    with pytest.raises(ValueError, match="no pilot terms"):
        current_terms(tmp_path / "empty")


def test_shipped_terms_are_a_placeholder_without_country_words():
    terms = current_terms()
    assert (CONSENT_DIR / "pilot.v1.md").is_file()
    assert terms.version == 1 and terms.placeholder is True
    assert "PLACEHOLDER" in terms.text and "pilot" in terms.text.lower() and "OpenAI" in terms.text
    assert "delete" in terms.text and "as the owners state it" in terms.text
    assert not COUNTRY_TERMS.search(terms.text)


def test_test_terms_are_not_a_placeholder():
    assert current_terms(TEST_TERMS).placeholder is False


def test_store_is_per_tenant(engine, clean):
    a, b = ConsentStore(engine, "pai"), ConsentStore(engine, "other")
    a.agree("stu-1", 1)
    a.agree("stu-1", 1)
    assert a.has("stu-1", 1) and not a.has("stu-1", 2) and not b.has("stu-1", 1) and not a.has("stu-2", 1)


def test_migration_up_down_up(os_db):
    from sqlalchemy import create_engine, inspect

    from app.os.db import OS_SCHEMA
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0014"], os_db)
    eng = create_engine(os_db)
    try:
        assert "os_consents" not in set(inspect(eng).get_table_names(schema=OS_SCHEMA))
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)


def test_placeholder_consent_from_rehearsal_does_not_pass_outside_it(engine, clean, os_db):
    """A rehearsal database reused with rehearsal off: a consent row for the placeholder must not let anyone in."""
    rehearsal = build_api(engine, os_db, terms_dir=None, rehearsal=True)
    version = rehearsal.get(f"{P}/consent", headers=me()).json()["version"]
    assert rehearsal.post(f"{P}/consent", json={"version": version}, headers=me()).status_code == 204
    clock.configure(None)
    pilot = build_api(engine, os_db, terms_dir=None)
    assert pilot.get(f"{P}/consent", headers=me()).json()["agreed"] is False
    r = raw_start(pilot)
    assert r.status_code == 409 and code(r) == "terms_not_set"
    up = raw_upload(pilot)
    assert up.status_code == 409 and code(up) == "terms_not_set"
    assert count(engine, models.plans) == 0 and count(engine, models.documents) == 0


@pytest.mark.parametrize("value", ["true", "'1'", "1.0"])
def test_terms_version_must_be_an_integer(tmp_path, value):
    (tmp_path / "pilot.v1.md").write_text(f"---\nversion: {value}\nplaceholder: false\n---\nx\n", encoding="utf-8")
    with pytest.raises(ValueError, match="version"):
        current_terms(tmp_path)
