"""Slice 6a Task 7: the manifest, the os.pack workflow, approval and the details form (spec S6a-D4, D7, D8, D10).
DBOS runs in this process, as in test_document_run. Synthetic files and fictional values only."""

import io
import json
from datetime import date, datetime, timezone

import pytest
from PIL import Image
from sqlalchemy import func, select, text, update

from app.os import models
from app.os.artifacts.store import ArtifactStore
from app.os.documents.store import DocumentStore
from app.os.kernel import Kernel
from app.os.knowledge import SEED_DIR, Fact, SqlKnowledge, load_seed
from app.os.packs.approval import PackIncomplete, PackNotCurrent, approve_pack, complete_review_tasks
from app.os.packs.config import load_pack_configs
from app.os.packs.details import save_details
from app.os.packs.inputs import inputs_sha, load_inputs
from app.os.packs.run import enqueue_pack, pack_workflow_id, register_packs
from app.os.packs.store import PackItemStore
from app.os.playbooks import load_playbook_dir
from app.os.service import PlanService
from app.os.settings import load_settings
from app.os.statements.config import load_statement_configs
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_golden import TEST_STUDENT

TENANT, ROUTE, YEAR = "pai", "germany_master", 2027
STUDENT, PROG, OTHER_PROG = TEST_STUDENT.student_ref, "ovgu-eeit", "tu-chemnitz-embedded-systems"
CFGS = load_pack_configs()
CFG = CFGS[ROUTE]
BOOKS = load_playbook_dir()
BOOK = next(b for (k, _), b in BOOKS.items() if k == ROUTE)
STMT = load_statement_configs()
ENTERED = {f.key: f"fictional {f.key}" for f in CFG.fields() if f.source == "entered"}
TICKS = {"degree", "transcript", "hssc", "ssc", "fee_paid"}
AT = datetime(2027, 3, 1, tzinfo=timezone.utc)


def jpeg(seed: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (900 + seed, 1200), ((seed * 37) % 256, (seed * 91) % 256, 200)).save(out, "JPEG")
    return out.getvalue()


class Ctx:
    def __init__(self, engine, client):
        self.engine, self.client = engine, client
        self.kb = SqlKnowledge(engine, TENANT)

    def inputs(self, programme=PROG):
        return load_inputs(self.engine, TENANT, self.kb, BOOK, CFG, STMT.get(ROUTE), STUDENT, programme, YEAR)

    def build(self, programme=PROG) -> dict:
        sha = inputs_sha(self.inputs(programme))
        wid = enqueue_pack(self.client, TENANT, STUDENT, programme, ROUTE, YEAR, sha)
        return self.client.retrieve_workflow(wid).get_result()

    def pack(self, programme=PROG):
        return next(a for a in ArtifactStore(self.engine, TENANT).list_for(STUDENT)
                    if a.kind == "pack" and a.programme_ref == programme)


@pytest.fixture
def packs(os_db, engine, clean):
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, TENANT))
    register_packs(engine, settings, SqlKnowledge(engine, TENANT), BOOKS, CFGS, STMT)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    ctx = Ctx(engine, client)
    load_seed(SEED_DIR / "germany_ws2027.yaml", ctx.kb)
    for prog in (PROG, OTHER_PROG):
        ctx.kb.upsert("programme", prog, "application_route",
                      Fact("uni_assist", "Apply via uni-assist.", "https://uni.example/apply", AT, YEAR, "confirmed"))
    try:
        yield ctx
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def ready_inputs(ctx: Ctx, ticks: set[str] = TICKS) -> None:
    """Every checklist item satisfied: confirmed documents, approved SOP and CV, entered details, ticks."""
    docs = DocumentStore(ctx.engine, TENANT)
    for n, item in enumerate((i for i in CFG.checklist if i.kind == "document"), 1):
        doc_id = docs.create(STUDENT, item.ref, 1, f"{item.ref}.jpg", "image/jpeg", jpeg(n))
        docs.set_status(doc_id, "confirmed")
    arts = ArtifactStore(ctx.engine, TENANT)
    for kind in ("sop", "cv"):
        a = arts.get_or_create(STUDENT, kind, None)
        arts.approve(a.id, arts.add_version(a.id, f"My fictional {kind} text.", "student").number)
    save_details(ctx.engine, TENANT, CFG, STUDENT, ENTERED)
    items = PackItemStore(ctx.engine, TENANT)
    for prog in (PROG, OTHER_PROG):
        for key in ticks:
            items.tick(STUDENT, prog, key)


def count(engine, table) -> int:
    with engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar()


def test_build_once_per_inputs(packs):
    ready_inputs(packs)
    first = packs.build()
    assert first["status"] == "ready"
    files = count(packs.engine, models.pack_files)
    assert packs.build() == first  # the same inputs: the same workflow, nothing new
    assert count(packs.engine, models.pack_files) == files
    assert len(ArtifactStore(packs.engine, TENANT).versions(packs.pack().id)) == 1


def test_replay_no_duplicate_files_or_versions(packs):
    ready_inputs(packs)
    packs.build()
    wid = pack_workflow_id(TENANT, STUDENT, PROG, inputs_sha(packs.inputs()))
    files = count(packs.engine, models.pack_files)
    forked = packs.client.fork_workflow(wid, 2)  # re-run every step after `start`, as a crash recovery would
    packs.client.retrieve_workflow(forked.workflow_id).get_result()
    assert count(packs.engine, models.pack_files) == files
    assert len(ArtifactStore(packs.engine, TENANT).versions(packs.pack().id)) == 1


def test_no_file_bytes_in_step_outputs(packs):
    ready_inputs(packs)
    packs.build()
    wid = pack_workflow_id(TENANT, STUDENT, PROG, inputs_sha(packs.inputs()))
    with packs.engine.connect() as conn:
        rows = conn.execute(text(f"SELECT function_name, length(coalesce(output, '')) FROM {TEST_DBOS_SCHEMA}"
                                 ".operation_outputs WHERE workflow_uuid = :w"), {"w": wid}).all()
    assert rows and all(n < 20_000 for _, n in rows), rows  # SHA-256s and the manifest, never a file


def test_incomplete_until_ready(packs):
    ready_inputs(packs, ticks=set())
    assert packs.build()["status"] == "incomplete"
    items = PackItemStore(packs.engine, TENANT)
    for key in TICKS:
        items.tick(STUDENT, PROG, key)
    assert packs.build()["status"] == "ready"


def test_approve_binds_manifest_sha(packs):
    ready_inputs(packs)
    built = packs.build()
    ap = approve_pack(packs.engine, Kernel(packs.engine, TENANT), TENANT, STUDENT, PROG, built["sha256"], None)
    store = ArtifactStore(packs.engine, TENANT)
    art = packs.pack()
    version = store.version(art.id, art.current_version)
    assert ap.sha256 == version.sha256 == built["sha256"] and art.status == "approved"
    manifest = json.loads(version.text)
    assert manifest["complete"] and {"data_sheet", "passport", "sop", "cv"} <= set(manifest["files"])
    approved_sop = store.approval(store.get_or_create(STUDENT, "sop", None).id).sha256
    assert manifest["statements"]["sop"] == approved_sop  # the approved SOP version is bound too


def test_stale_or_incomplete_approve_refused(packs):
    ready_inputs(packs, ticks=set())
    built = packs.build()
    kernel = Kernel(packs.engine, TENANT)
    with pytest.raises(PackIncomplete):
        approve_pack(packs.engine, kernel, TENANT, STUDENT, PROG, built["sha256"], None)
    with pytest.raises(PackNotCurrent):
        approve_pack(packs.engine, kernel, TENANT, STUDENT, PROG, "0" * 64, None)
    with pytest.raises(PackNotCurrent):
        approve_pack(packs.engine, kernel, TENANT, STUDENT, "no-such-programme", built["sha256"], None)


def test_entered_change_drops_approval(packs):
    """Review Focus #1: a detail changed after approval gives a new version and drops the approval."""
    ready_inputs(packs)
    first = packs.build()
    approve_pack(packs.engine, Kernel(packs.engine, TENANT), TENANT, STUDENT, PROG, first["sha256"], None)
    save_details(packs.engine, TENANT, CFG, STUDENT, {"phone": "+00 000 0001"})
    second = packs.build()
    assert second["sha256"] != first["sha256"] and second["status"] == "ready"
    store = ArtifactStore(packs.engine, TENANT)
    assert store.approval(packs.pack().id) is None and packs.pack().current_version == 2


def test_same_file_two_items_one_blob(packs):
    """Review Focus #2 (as ruled): one document in two programmes' packs is stored once."""
    ready_inputs(packs)
    packs.build(PROG)
    packs.build(OTHER_PROG)
    with packs.engine.connect() as conn:
        passports = conn.execute(select(func.count()).select_from(models.pack_files)
                                 .where(models.pack_files.c.item_key == "passport")).scalar()
    assert passports == 1


def test_review_pack_task_completes_via_kernel(packs):
    ready_inputs(packs)
    svc = PlanService(packs.engine, load_settings({"OS_DATABASE_URL": "postgresql://unused/x"}),
                      Kernel(packs.engine, TENANT), packs.kb, BOOKS, today=lambda: date(2027, 2, 1))
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    T = models.tasks
    with packs.engine.begin() as conn:  # the task's turn has come (the kernel's promotion, simulated)
        conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.instance_key == f"review_pack@{PROG}")
                     .values(state="waiting_student"))
    built = packs.build()
    approve_pack(packs.engine, Kernel(packs.engine, TENANT), TENANT, STUDENT, PROG, built["sha256"], plan_id)
    with packs.engine.connect() as conn:
        state, result = conn.execute(select(T.c.state, T.c.result).where(
            T.c.plan_id == plan_id, T.c.instance_key == f"review_pack@{PROG}")).one()
    assert state == "done" and result["artifacts"]["pack"] == built["sha256"]


def test_task_ready_later_completes_on_get(packs):
    ready_inputs(packs)
    svc = PlanService(packs.engine, load_settings({"OS_DATABASE_URL": "postgresql://unused/x"}),
                      Kernel(packs.engine, TENANT), packs.kb, BOOKS, today=lambda: date(2027, 2, 1))
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    built = packs.build()
    kernel = Kernel(packs.engine, TENANT)
    approve_pack(packs.engine, kernel, TENANT, STUDENT, PROG, built["sha256"], plan_id)  # the task is not ready yet
    T = models.tasks
    with packs.engine.begin() as conn:
        conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.instance_key == f"review_pack@{PROG}")
                     .values(state="waiting_student"))
    assert len(complete_review_tasks(packs.engine, kernel, TENANT, STUDENT, plan_id)) == 1


def test_delete_document_drops_its_pack_files(packs):
    from app.os.documents.checks import load_name_variants
    from app.os.documents.confirm import delete_document
    from app.os.documents.types import load_document_types

    ready_inputs(packs)
    packs.build()
    docs = DocumentStore(packs.engine, TENANT)
    passport = next(d for d in docs.list_for(STUDENT) if d.doc_type == "passport")
    delete_document(packs.engine, TENANT, load_document_types(), load_name_variants(), passport, client=packs.client)
    with packs.engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.pack_files)
                            .where(models.pack_files.c.item_key == "passport")).scalar() == 0
    assert packs.build()["status"] == "incomplete"


def test_details_refuses_unknown_keys(packs):
    with pytest.raises(ValueError, match="surname"):
        save_details(packs.engine, TENANT, CFG, STUDENT, {"surname": "typed over a document value"})
    with pytest.raises(ValueError, match="shoe_size"):
        save_details(packs.engine, TENANT, CFG, STUDENT, {"shoe_size": "9"})


def test_render_failure_marks_failed(packs, monkeypatch):
    from app.os.packs import render

    def broken(*_args, **_kw):
        raise RuntimeError("renderer down")

    monkeypatch.setattr(render, "render_sheet", broken)
    ready_inputs(packs)
    assert packs.build()["status"] == "failed"
    assert packs.pack().status == "failed"
