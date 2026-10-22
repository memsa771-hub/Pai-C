"""Slice 6b (plan Task 3, built fourth): the visa file as a second kind of pack: the choice, inputs with funds, the
workflow and approval (spec S6b-D2, D4, D7, D8, D9). DBOS in this process. Fictional values only."""

import io
import json
from datetime import date

import pytest
from PIL import Image
from sqlalchemy import create_engine, inspect, select, update

from app.os import models
from app.os.artifacts.store import ArtifactStore
from app.os.db import OS_SCHEMA
from app.os.documents.store import DocumentStore, ProfileStore
from app.os.kernel import Kernel
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.packs.approval import approve_pack
from app.os.packs.config import load_pack_configs
from app.os.packs.details import save_details
from app.os.packs.inputs import inputs_sha, load_inputs
from app.os.packs.run import enqueue_pack, pack_workflow_id, register_packs
from app.os.packs.store import PackItemStore
from app.os.packs.visa import VISA_ITEMS, VisaChoiceStore, preselect
from app.os.playbooks import load_playbook_dir
from app.os.service import PlanService
from app.os.settings import load_settings
from app.os.statements.config import load_statement_configs
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_golden import TEST_STUDENT

TENANT, ROUTE, YEAR = "pai", "germany_master", 2027
STUDENT, PROG, OTHER = TEST_STUDENT.student_ref, "ovgu-eeit", "tu-chemnitz-embedded-systems"
PACKS, VISAS = load_pack_configs(), load_pack_configs(kind="visa")
VISA = VISAS[ROUTE]
BOOKS = load_playbook_dir()
BOOK = next(b for (k, _), b in BOOKS.items() if k == ROUTE)
STMT = load_statement_configs()
TICKS = {"degree", "transcript", "portal_applied", "visa_fee_paid"}


def jpeg(seed: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (900 + seed, 1200), ((seed * 41) % 256, (seed * 73) % 256, 190)).save(out, "JPEG")
    return out.getvalue()


class Ctx:
    def __init__(self, engine, client):
        self.engine, self.client, self.kb = engine, client, SqlKnowledge(engine, TENANT)

    def inputs(self, kind="visa", programme=PROG):
        cfg = (VISAS if kind == "visa" else PACKS)[ROUTE]
        return load_inputs(self.engine, TENANT, self.kb, BOOK, cfg, STMT.get(ROUTE), STUDENT, programme, YEAR, kind)

    def build(self, kind="visa", programme=None) -> dict:
        programme = programme or (VisaChoiceStore(self.engine, TENANT).get(STUDENT).programme_ref
                                  if kind == "visa" else PROG)
        sha = inputs_sha(self.inputs(kind, programme))
        art = self.art(kind, programme)
        version = (art.current_version or 0) if art else 0
        wid = enqueue_pack(self.client, TENANT, STUDENT, programme, ROUTE, YEAR, sha, version, 0, kind)
        return self.client.retrieve_workflow(wid).get_result()

    def art(self, kind="visa", programme=PROG):
        want = None if kind == "visa" else programme
        return next((a for a in ArtifactStore(self.engine, TENANT).list_for(STUDENT)
                     if a.kind == kind and a.programme_ref == want), None)


@pytest.fixture
def visa(os_db, engine, clean):
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA})
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), Kernel(engine, TENANT))
    register_packs(engine, settings, SqlKnowledge(engine, TENANT), BOOKS, PACKS, STMT, VISAS)
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    ctx = Ctx(engine, client)
    load_seed(SEED_DIR / "germany_ws2027.yaml", ctx.kb)  # holds the route fact blocked_account_yearly_eur
    try:
        yield ctx
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


def ready_visa(ctx: Ctx, amount: float = 11904.0) -> None:
    docs, profile = DocumentStore(ctx.engine, TENANT), ProfileStore(ctx.engine, TENANT)
    for n, item in enumerate((i for i in VISA.checklist if i.kind == "document"), 1):
        doc_id = docs.create(STUDENT, item.ref, 1, f"{item.ref}.jpg", "image/jpeg", jpeg(n))
        docs.set_status(doc_id, "confirmed")
        if item.ref == "blocked_account_confirmation":
            profile.set(STUDENT, "blocked_account_confirmation.amount", amount, doc_id)
    arts = ArtifactStore(ctx.engine, TENANT)
    for kind in ("sop", "cv"):
        a = arts.get_or_create(STUDENT, kind, None)
        arts.approve(a.id, arts.add_version(a.id, f"My fictional {kind}.", "student").number)
    save_details(ctx.engine, TENANT, VISA, STUDENT,
                 {f.key: f"fictional {f.key}" for f in VISA.fields() if f.source == "entered"})
    VisaChoiceStore(ctx.engine, TENANT).set_programme(STUDENT, PROG)
    for key in TICKS:
        PackItemStore(ctx.engine, TENANT).tick(STUDENT, VISA_ITEMS, key)


def test_migration_up_down_up(os_db):
    from tests.os.conftest import run_alembic

    run_alembic(["downgrade", "os_0010"], os_db)
    eng = create_engine(os_db)
    try:
        assert "os_visa_choices" not in set(inspect(eng).get_table_names(schema=OS_SCHEMA))
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)


def test_visa_build_and_funds_in_manifest(visa):
    ready_visa(visa)
    built = visa.build()
    assert built["status"] == "ready", built
    art = visa.art()
    manifest = json.loads(ArtifactStore(visa.engine, TENANT).version(art.id, art.current_version).text)
    assert manifest["programme"] == PROG and manifest["funds"]["required"] == 11904.0
    assert manifest["funds"]["status"] == "unconfirmed" and manifest["funds"]["url"].startswith("https://")
    assert {"motivation_letter", "blocked_account", "admission"} <= set(manifest["files"])


def test_pack_and_visa_are_separate(visa):
    """Review Focus #4: a pack and a visa file for one programme are two artifacts; approving one is not the other."""
    ready_visa(visa)
    assert visa.inputs("pack").kind == "pack" and visa.inputs("visa").kind == "visa"
    pack, file = visa.build("pack", PROG), visa.build("visa")
    assert visa.art("pack") is not None and visa.art("visa") is not None and visa.art("pack").id != visa.art("visa").id
    approve_pack(visa.engine, Kernel(visa.engine, TENANT), TENANT, STUDENT, None, file["sha256"], None, kind="visa")
    assert ArtifactStore(visa.engine, TENANT).approval(visa.art("pack").id) is None
    assert pack["sha256"] != file["sha256"]


def test_choice_change_drops_approval(visa):
    """Review Focus #1: another programme after approving rebuilds the file and drops the approval."""
    ready_visa(visa)
    first = visa.build()
    approve_pack(visa.engine, Kernel(visa.engine, TENANT), TENANT, STUDENT, None, first["sha256"], None, kind="visa")
    VisaChoiceStore(visa.engine, TENANT).set_programme(STUDENT, OTHER)
    second = visa.build()
    assert second["sha256"] != first["sha256"]
    assert ArtifactStore(visa.engine, TENANT).approval(visa.art().id) is None
    art = visa.art()
    assert json.loads(ArtifactStore(visa.engine, TENANT).version(art.id, art.current_version).text)["programme"] == OTHER


def test_reduction_change_rebuilds(visa):
    ready_visa(visa, amount=9000.0)
    assert visa.build()["status"] == "incomplete"  # 9000 is below 11904
    VisaChoiceStore(visa.engine, TENANT).set_reduction(STUDENT, 3000)
    assert visa.build()["status"] == "ready"  # 11904 - 3000 = 8904 <= 9000
    with pytest.raises(ValueError):
        VisaChoiceStore(visa.engine, TENANT).set_reduction(STUDENT, -1)


def test_preselect_admitted(visa):
    svc = PlanService(visa.engine, load_settings({"OS_DATABASE_URL": "postgresql://unused/x"}),
                      Kernel(visa.engine, TENANT), visa.kb, BOOKS, today=lambda: date(2027, 2, 1))
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    assert preselect(visa.engine, TENANT, plan_id) is None
    T = models.tasks
    with visa.engine.begin() as conn:  # the student told us this programme admitted them (the kernel's write, simulated)
        conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.instance_key == f"admission_result@{OTHER}")
                     .values(state="done", result={"choice": "admitted"}))
    assert preselect(visa.engine, TENANT, plan_id) == OTHER


def test_visa_replay_idempotent(visa):
    ready_visa(visa)
    visa.build()
    wid = pack_workflow_id(TENANT, STUDENT, PROG, inputs_sha(visa.inputs()), 0, 0, "visa")
    assert wid.startswith("visa:")
    forked = visa.client.fork_workflow(wid, 2)
    visa.client.retrieve_workflow(forked.workflow_id).get_result()
    assert len(ArtifactStore(visa.engine, TENANT).versions(visa.art().id)) == 1


def test_approve_visa_completes_review_visa_file(visa):
    ready_visa(visa)
    svc = PlanService(visa.engine, load_settings({"OS_DATABASE_URL": "postgresql://unused/x"}),
                      Kernel(visa.engine, TENANT), visa.kb, BOOKS, today=lambda: date(2027, 2, 1))
    plan_id = svc.start_plan(TEST_STUDENT).plan_id
    T = models.tasks
    with visa.engine.begin() as conn:
        conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.instance_key == "review_visa_file")
                     .values(state="waiting_student"))
    built = visa.build()
    approve_pack(visa.engine, Kernel(visa.engine, TENANT), TENANT, STUDENT, None, built["sha256"], plan_id, kind="visa")
    with visa.engine.connect() as conn:
        state, result = conn.execute(select(T.c.state, T.c.result).where(
            T.c.plan_id == plan_id, T.c.instance_key == "review_visa_file")).one()
    assert state == "done" and result["artifacts"]["visa"] == built["sha256"]


def test_programme_in_visa_fingerprint(visa):
    """Two programmes can share every fact: the visa file's fingerprint still differs, so an old tab is refused."""
    ready_visa(visa)
    from dataclasses import replace

    a = visa.inputs(programme=PROG)
    b = replace(visa.inputs(programme=OTHER), facts=a.facts)
    assert inputs_sha(a) != inputs_sha(b)
