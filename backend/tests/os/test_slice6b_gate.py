"""The Slice 6b gate (spec §8, §9): on Germany, a test student goes from confirmed documents (the three new types
among them, with a blocked-account amount that covers the requirement), approved statements, typed details, a chosen
programme and ticks to an approved visa file, and the plan's review_visa_file task is done. The fake routes have no
visa page. os.pack runs in this process. Fictional data."""

import time
from datetime import date

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.os import models
from app.os.api import build_router, current_student_ref, current_student_ref_for_write, make_services
from app.os.artifacts.store import ArtifactStore
from app.os.documents.store import DocumentStore, ProfileStore
from app.os.kernel import Kernel
from app.os.knowledge import SEED_DIR, Fact, SqlKnowledge, load_seed
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.packs.config import load_pack_configs
from app.os.packs.run import register_packs
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.settings import load_settings
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_slice6a_gate import CHECKED, CONFIGS, HERE, ROUTES, STATEMENTS, jpeg
from tests.os.test_api import TEST_TERMS, agree

VISAS = load_pack_configs(kind="visa")
P = "/v1/os"
ME = {"X-Test-Student": "stu-1"}
T = models.tasks
GERMANY = ["g1", "g2"]


@pytest.fixture
def api(engine, clean, os_db):
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA, "OS_ENABLED": "true"})
    books = load_playbook_dir(HERE / "playbooks") | load_playbook_dir(PLAYBOOK_DIR)
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, "pai"))
    register_packs(engine, settings, SqlKnowledge(engine, "pai"), books, CONFIGS, STATEMENTS, VISAS)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    svc = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1),
                        dbos_client=lambda: client, statement_configs=STATEMENTS, pack_configs=CONFIGS,
                        visa_configs=VISAS, terms_dir=TEST_TERMS)
    kb, store = SqlKnowledge(engine, "pai"), ProgrammeStore(engine, "pai")
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)  # the route's funds fact
    for route, refs in {**{r: [ref] for r, (ref, _) in ROUTES.items()}, "germany_master": GERMANY}.items():
        for ref in refs:  # programmes the student can choose, with the facts the instructions use
            store.upsert(Programme(ref=ref, route_key=route, university="Uni X", name=f"Programme {ref}", aliases=(),
                                   start_urls=(f"https://uni.example/{ref}",), official_domains=("uni.example",)))
            facts = {"application_route": next(iter(CONFIGS[route].instructions)), **ROUTES[route][1]}
            for field, value in facts.items():
                kb.upsert("programme", ref, field, Fact(value, "q", "https://uni.example/r", CHECKED, 2027,
                                                        "confirmed"), "manual")
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


def settled(api, timeout: float = 60) -> dict:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = api.get(f"{P}/visa", headers=ME).json()
        if body["status"] != "building":
            return body
        time.sleep(0.3)
    raise AssertionError("the visa file was not built in time")


def test_slice6b_gate(api):
    cfg = VISAS["germany_master"]
    programmes = GERMANY

    # 1. the student's Germany plan, with the visa step waiting for them (the kernel's promotion, simulated)
    agree(api)
    r = api.post(f"{P}/plans/self", headers=ME, json={
        "route": "germany_master", "intake": {"term": "winter", "year": 2027},
        "choices": [{"programme_ref": ref, "rank": n} for n, ref in enumerate(programmes, 1)]})
    assert r.status_code == 201, r.text
    plan_id = r.json()["plan_id"]
    with api.engine.begin() as conn:
        conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.template_key == "review_visa_file")
                     .values(state="waiting_student"))

    # 2. no programme yet: nothing to build, the funds already shown, approval refused
    first = api.get(f"{P}/visa", headers=ME).json()
    assert first["status"] == "no_choice" and first["funds"]["required"] > 0
    assert api.post(f"{P}/visa/approve", headers=ME, json={"sha256": "0" * 64}).status_code == 409

    # 3. the student chooses the programme that admitted them
    assert api.put(f"{P}/visa/choice", headers=ME, json={"programme_ref": programmes[1]}).status_code == 200
    assert settled(api)["status"] == "incomplete"

    # 4. the student's material: confirmed documents (the blocked account covers the requirement), approved
    #    statements, typed details, and the ticks only they can give
    required = first["funds"]["required"]
    docs, profile, doc_ids = DocumentStore(api.engine, "pai"), ProfileStore(api.engine, "pai"), {}
    for n, item in enumerate((i for i in cfg.checklist if i.kind == "document"), 1):
        doc_ids[item.ref] = docs.create("stu-1", item.ref, 1, f"{item.ref}.jpg", "image/jpeg", jpeg(n))
        docs.set_status(doc_ids[item.ref], "confirmed")
    proof = f"{next(i.ref for i in cfg.checklist if i.key == cfg.funds.proof_item)}.{cfg.funds.proof_field}"
    for f in cfg.fields():  # what confirming those documents writes to the profile (Slice 3), with its source
        if f.source != "entered":
            doc_type = f.source.split(".")[0]
            doc_id = doc_ids.get(doc_type) or docs.create("stu-1", doc_type, 1, f"{doc_type}.jpg", "image/jpeg",
                                                          jpeg(100 + len(doc_ids)))
            doc_ids[doc_type] = doc_id
            profile.set("stu-1", f.source, f"{required:,.2f}" if f.source == proof else f"fictional {f.key}", doc_id)
    arts = ArtifactStore(api.engine, "pai")
    for kind in ("sop", "cv"):
        a = arts.get_or_create("stu-1", kind, None)
        arts.approve(a.id, arts.add_version(a.id, f"My fictional {kind}.", "student").number)
    entered = {f.key: f"fictional {f.key}" for f in cfg.fields() if f.source == "entered"}
    assert api.put(f"{P}/visa/details", headers=ME, json={"fields": entered}).status_code == 200
    tickable = [i["key"] for i in settled(api)["checklist"] if i["tickable"]]
    assert api.put(f"{P}/visa/items", headers=ME, json={"tick": tickable}).status_code == 200

    # 5. complete: every file is there, the data sheet has no gap, and the student approves this exact version
    visa = settled(api)
    assert visa["status"] == "ready", [i for i in visa["checklist"] if i["state"] not in ("ready", "manual")]
    assert visa["programme_ref"] == programmes[1] and not [r for r in visa["data_sheet"] if r["gap"]]
    keys = {f["key"] for f in visa["files"]}
    assert "data_sheet" in keys and {i.key for i in cfg.checklist if i.kind in ("document", "statement")} <= keys
    for f in visa["files"]:
        got = api.get(f"{P}/visa/files/{f['sha256']}", headers=ME)
        assert got.status_code == 200 and got.content.startswith(b"%PDF-")
    r = api.post(f"{P}/visa/approve", headers=ME, json={"sha256": visa["manifest_sha256"]})
    assert r.status_code == 200, r.text

    # 6. the plan's visa step is done, bound to the approved manifest; the pack's step is untouched
    with api.engine.connect() as conn:
        rows = {t: (s, res) for t, s, res in conn.execute(select(T.c.template_key, T.c.state, T.c.result).where(
            T.c.plan_id == plan_id, T.c.template_key.in_(["review_visa_file", "review_pack"]))).all()}
    state, result = rows["review_visa_file"]
    assert state == "done" and result["artifacts"]["visa"] == visa["manifest_sha256"]
    assert rows["review_pack"][0] != "done"
    assert settled(api)["approved"] is True


@pytest.mark.parametrize("route", ["ireland_master", "pakistan_bs"])
def test_fake_routes_have_no_visa_page(api, route):
    programme, _ = ROUTES[route]
    agree(api)
    r = api.post(f"{P}/plans/self", headers=ME, json={"route": route, "intake": {"term": "winter", "year": 2027},
                                                      "choices": [{"programme_ref": programme, "rank": 1}]})
    assert r.status_code == 201, r.text
    got = api.get(f"{P}/visa", headers=ME)
    assert got.status_code == 404 and "visa" in got.json()["detail"]
