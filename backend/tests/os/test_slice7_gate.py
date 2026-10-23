"""The Slice 7 gate (spec "Done when"): every scripted event in `replan_cases.yaml` gives the right change, on
Germany and the fake Ireland and Pakistan BS routes, with no code change between routes. os.replan runs in this
process; the Supervisor is a FunctionModel replaying each case's recorded answer. Fictional data."""

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from sqlalchemy import select, update

from app.os import models
from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import Kernel
from app.os.knowledge import SEED_DIR, SqlKnowledge, load_seed
from app.os.outbox import Outbox
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.replan import events
from app.os.replan.apply import Replanner
from app.os.replan.config import load_replan_configs
from app.os.replan.run import enqueue_replan, register_replan
from app.os.replan.store import ProposalStore, SupportStore
from app.os.replan.supervisor import build_supervisor
from app.os.service import PlanService
from app.os.settings import load_settings
from tests.os.conftest import TEST_DBOS_SCHEMA, reset_dbos_schema
from tests.os.test_golden import TEST_STUDENT

HERE = Path(__file__).parent
CASES = yaml.safe_load((HERE / "replan_cases.yaml").read_text(encoding="utf-8"))
ROUTES = {"germany_master": ("DE", "master"), "ireland_master": ("IE", "master"), "pakistan_bs": ("PK", "bachelor")}
NOW = datetime(2027, 2, 1, 9, tzinfo=timezone.utc)
T = models.tasks
ANSWER: dict = {}  # the current case's recorded Supervisor answer


def replay(messages, info: AgentInfo) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, ANSWER["value"])])


def contract(route: str, programmes: list[str]) -> RouteContract:
    if route == "germany_master":
        return TEST_STUDENT
    dest, level = ROUTES[route]
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": f"gate-{route}", "student_ref": "stu-gate",
        "origin_country": "PK", "destination_country": dest, "level": level,
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i} for i, r in enumerate(programmes, 1)]})


@pytest.fixture(scope="module")
def books():
    return load_playbook_dir(HERE / "playbooks") | load_playbook_dir(PLAYBOOK_DIR)


@pytest.fixture
def gate(os_db, engine, clean, books):
    from dbos import DBOS, DBOSClient

    from app.os.runner import APP_NAME, dbos_config, default_registry, launch, register_workflow

    reset_dbos_schema(os_db)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_DBOS_SYSTEM_SCHEMA": TEST_DBOS_SCHEMA,
                              "OS_PRICE_STRONG_IN": "2.5", "OS_PRICE_STRONG_CACHED": "0.25",
                              "OS_PRICE_STRONG_OUT": "15"})
    kb = SqlKnowledge(engine, "pai")
    load_seed(SEED_DIR / "germany_ws2027.yaml", kb)
    kernel = Kernel(engine, "pai", clock=lambda: NOW)
    plans = PlanService(engine, settings, kernel, kb, books, today=lambda: NOW.date())
    replanner = Replanner(engine, plans, load_replan_configs(), Outbox(engine, "pai"), clock=lambda: NOW)
    spec = load_agent_spec(AGENT_DIR / "supervisor.v1.yaml")
    DBOS(config=dbos_config(settings, "test-w0"))
    register_workflow(engine, settings, default_registry(), kernel)
    register_replan(engine, settings, replanner, (build_supervisor(FunctionModel(replay), spec), spec))
    launch()
    client = DBOSClient(system_database_url=os_db, dbos_system_schema=TEST_DBOS_SCHEMA, application_name=APP_NAME)
    try:
        yield replanner, client
    finally:
        client.destroy()
        DBOS.destroy(destroy_registry=True)


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_slice7_gate(gate, engine, case):
    replanner, client = gate
    ANSWER["value"] = case.get("supervisor", {"ops": [{"op": "escalate", "reason": "x"}], "summary": "?"})
    c = contract(case["route"], case.get("programmes", []))
    plan_id = replanner.plans.start_plan(c).plan_id
    for key, state in (case.get("states") or {}).items():
        with engine.begin() as conn:
            conn.execute(update(T).where(T.c.plan_id == plan_id, T.c.instance_key == key).values(state=state))
    payload = {k: v for k, v in case["event"].items() if k != "type"}
    with engine.begin() as conn:
        eid = events.record(conn, "pai", plan_id, case["event"]["type"], payload, case["id"])
    got = client.retrieve_workflow(enqueue_replan(client, "pai", plan_id, eid)).get_result()
    want = case["expect"]
    assert got["status"] == want["status"], got
    p = ProposalStore(engine, "pai").get(got["proposal_id"]) if got.get("proposal_id") else None
    if "ops" in want:
        assert [o["op"] for o in p.ops] == want["ops"]
    if "ops_include" in want:
        assert set(want["ops_include"]) <= {o["op"] for o in p.ops}
    if "source" in want:
        assert p.source == want["source"]
    if want.get("support"):
        assert [s for s in SupportStore(engine, "pai").list("open") if s.plan_id == plan_id]
    if "outbox" in want:
        with engine.connect() as conn:
            keys = conn.execute(select(models.outbox.c.idempotency_key)).scalars().all()
        assert f"replan:{p.id}:{want['outbox']}" in keys
    if "task" in want:
        with engine.connect() as conn:
            assert conn.execute(select(T.c.id).where(T.c.plan_id == plan_id,
                                                     T.c.instance_key == want["task"])).first()
    if want.get("accept"):
        replanner.accept(c.student_ref, p.id)
        with engine.connect() as conn:
            live = conn.execute(select(T.c.id).where(T.c.plan_id == plan_id,
                                                     T.c.programme_ref == want["cancelled_programme"],
                                                     T.c.state != "cancelled")).all()
        assert live == []
    assert events.pending(engine, "pai", plan_id) == []  # every event is handled


def test_fake_routes_unchanged_without_events(gate, engine, books):
    """Without events nothing replans: the fake routes' plans are exactly what Slice 1 compiles."""
    replanner, _ = gate
    for route in ("ireland_master", "pakistan_bs"):
        c = contract(route, ["x1", "x2"])
        plan_id = replanner.plans.start_plan(c).plan_id
        assert replanner.proposals.for_plan(plan_id) == []
        assert replanner.plans.recompile(plan_id, "deadline_recompute") is None
    assert date(2027, 2, 1) == NOW.date()
