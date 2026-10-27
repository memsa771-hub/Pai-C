"""The Slice 6a gate (spec §8 test 9, §9): on Germany, the fake Ireland route and the fake Pakistan BS route, a test
student goes from confirmed documents, approved statements and typed details to a complete, approved pack, and the
plan's review_pack task is done, with no code change between routes. os.pack runs in this process. Fictional data."""

import io
import time
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select, update

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.artifacts.store import ArtifactStore
from app.os.documents.store import DocumentStore, ProfileStore
from app.os.kernel import Kernel
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.packs.config import load_pack_configs
from app.os.packs.run import register_packs
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings
from app.os.statements.config import load_statement_configs
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_api import TEST_TERMS, agree

HERE = Path(__file__).parent
CONFIGS = load_pack_configs() | load_pack_configs(HERE / "fixtures" / "packs")
STATEMENTS = load_statement_configs() | load_statement_configs(HERE / "statements")
CHECKED = datetime(2027, 3, 1, tzinfo=timezone.utc)
P = "/v1/os"
ME = {"X-Test-Student": "stu-1"}
# per route: its programme and the facts the instructions use (the route value is the config's first)
ROUTES = {
    "germany_master": ("g1", {"deadline_close": {"date": "2027-07-15"}}),
    "ireland_master": ("i1", {"deadline_close": {"date": "2027-06-30"}, "application_fee": 50}),
    "pakistan_bs": ("k1", {"merit_list_date": {"date": "2027-08-01"}}),
}


def jpeg(seed: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (800 + seed, 1100), ((seed * 53) % 256, (seed * 29) % 256, 180)).save(out, "JPEG")
    return out.getvalue()


@pytest.fixture
def api(engine, clean, os_db):
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA, "OS_ENABLED": "true"})
    books = load_playbook_dir(HERE / "playbooks") | load_playbook_dir(PLAYBOOK_DIR)
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, "pai"))
    register_packs(engine, settings, SqlKnowledge(engine, "pai"), books, CONFIGS, STATEMENTS)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1),
                        dbos_client=lambda: client, statement_configs=STATEMENTS, pack_configs=CONFIGS,
                        terms_dir=TEST_TERMS)
    store, kb = ProgrammeStore(engine, "pai"), SqlKnowledge(engine, "pai")
    for route, (ref, facts) in ROUTES.items():
        store.upsert(Programme(ref=ref, route_key=route, university="Uni X", name=f"Programme {ref}", aliases=(),
                               start_urls=(f"https://uni.example/{ref}",), official_domains=("uni.example",)))
        route_value = next(iter(CONFIGS[route].instructions))
        for field, value in {"application_route": route_value, **facts}.items():
            kb.upsert("programme", ref, field, Fact(value, "q", "https://uni.example/r", CHECKED, 2027, "confirmed"),
                      "manual")
    app = FastAPI()
    app.include_router(build_router(lambda: svc), prefix=P)

    def student(x_test_student: str | None = Header(None)) -> str:
        if not x_test_student:
            raise HTTPException(401)
        return x_test_student

    app.dependency_overrides[current_student_ref] = student
    app.dependency_overrides[current_student_ref_for_write] = student
    c = TestClient(app)
    c.engine = engine
    try:
        yield c
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def settled(api, programme: str, timeout: float = 60) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = {p["programme_ref"]: p for p in api.get(f"{P}/packs", headers=ME).json()["programmes"]}
        if found[programme]["status"] != "building":
            return found[programme]
        time.sleep(0.3)
    raise AssertionError("the pack was not built in time")


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_slice6a_gate(api, route):
    programme, _ = ROUTES[route]
    cfg = CONFIGS[route]

    # 1. the student's plan, with the pack step waiting for them (the kernel's promotion, simulated)
    agree(api)
    r = api.post(f"{P}/plans/self", headers=ME, json={"route": route, "intake": {"term": "winter", "year": 2027},
                                                      "choices": [{"programme_ref": programme, "rank": 1}]})
    assert r.status_code == 201, r.text
    plan_id = r.json()["plan_id"]
    T = models.tasks
    with api.engine.begin() as conn:
        conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.template_key == "review_pack")
                     .values(state="waiting_student"))

    # 2. nothing yet: the pack lists every gap, and cannot be approved
    first = settled(api, programme)
    assert first["status"] == "incomplete"
    assert api.post(f"{P}/packs/{programme}/approve", headers=ME,
                    json={"sha256": first["manifest_sha256"]}).status_code == 409

    # 3. the student's material: confirmed documents, approved statements, typed details
    docs, profile, doc_ids = DocumentStore(api.engine, "pai"), ProfileStore(api.engine, "pai"), {}
    for n, item in enumerate((i for i in cfg.checklist if i.kind == "document"), 1):
        doc_ids[item.ref] = docs.create("stu-1", item.ref, 1, f"{item.ref}.jpg", "image/jpeg", jpeg(n))
        docs.set_status(doc_ids[item.ref], "confirmed")
    for f in cfg.fields():  # what confirming those documents writes to the profile (Slice 3), with its source
        if f.source != "entered":
            doc_type = f.source.split(".")[0]
            doc_id = doc_ids.get(doc_type) or docs.create("stu-1", doc_type, 1, f"{doc_type}.jpg", "image/jpeg",
                                                          jpeg(100 + len(doc_ids)))
            doc_ids[doc_type] = doc_id
            profile.set("stu-1", f.source, f"fictional {f.key}", doc_id)
    arts = ArtifactStore(api.engine, "pai")
    for kind in sorted({i.ref for i in cfg.checklist if i.kind == "statement"}):
        a = arts.get_or_create("stu-1", kind, None)
        arts.approve(a.id, arts.add_version(a.id, f"My fictional {kind}.", "student").number)
    entered = {f.key: f"fictional {f.key}" for f in cfg.fields() if f.source == "entered"}
    assert api.put(f"{P}/packs/details", headers=ME, json={"fields": entered}).status_code == 200

    # 4. the ticks only the student can give (manual items, attested copies)
    tickable = [i["key"] for i in settled(api, programme)["checklist"] if i["tickable"]]
    assert api.put(f"{P}/packs/{programme}/items", headers=ME, json={"tick": tickable}).status_code == 200

    # 5. complete: every file is there, the data sheet has no gap, and the student approves this exact version
    pack = settled(api, programme)
    assert pack["status"] == "ready", [i for i in pack["checklist"] if i["state"] not in ("ready", "manual")]
    assert not [r for r in pack["data_sheet"] if r["gap"]]
    keys = {f["key"] for f in pack["files"]}
    assert "data_sheet" in keys and {i.key for i in cfg.checklist if i.kind in ("document", "statement")} <= keys
    for f in pack["files"]:
        got = api.get(f"{P}/packs/{programme}/files/{f['sha256']}", headers=ME)
        assert got.status_code == 200 and got.content.startswith(b"%PDF-")
    r = api.post(f"{P}/packs/{programme}/approve", headers=ME, json={"sha256": pack["manifest_sha256"]})
    assert r.status_code == 200, r.text

    # 6. where the route's plan has the pack step, it is done, bound to the approved manifest (route data: the fake
    #    routes' shared plans have none, and their packs are still complete and approved)
    with api.engine.connect() as conn:
        row = conn.execute(select(T.c.state, T.c.result).where(
            T.c.plan_id == plan_id, T.c.template_key == "review_pack")).first()
    if route == "germany_master":
        assert row is not None and row.state == "done" and row.result["artifacts"]["pack"] == pack["manifest_sha256"]
    else:
        assert row is None
    assert settled(api, programme)["approved"] is True
