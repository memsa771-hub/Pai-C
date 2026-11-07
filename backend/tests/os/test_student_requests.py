"""P1-T8 Task 3: one open request per student and fact (R-19), kept in step with the plan's request steps by the kernel;
a request is never ticked by hand (R-18); the student lists their own (D-w19). Real kernel and Postgres; fictional
route and student."""

import threading
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import insert, inspect, select
from sqlalchemy.exc import IntegrityError

from app.os import inbox_actions, models, ports
from app.os.compiler import compile_plan
from app.os.inbox_actions import StepActionError
from app.os.requests import store, texts
from app.os.requests.state import StudentState
from tests.os.kernel_helpers import kernel
from tests.os.test_compile_needs import CALENDAR, INTER2, OBTAINED, TOTAL, contract, merit
from tests.os.test_needs_gate import api, contract as gate_contract, facts_of, world  # noqa: F401  (fixtures)
from tests.os.test_api import as_student

TODAY = datetime(2027, 3, 1).date()
NOTHING = StudentState()
TYPED = StudentState(facts={OBTAINED: "stated", TOTAL: "stated"})
R = models.student_requests

pytestmark = pytest.mark.req("R-19")


def compiled(state, route_facts=None):
    return compile_plan(contract(), INTER2, route_facts or {}, merit(), TODAY, student=state)


def contract_of(ref: str):
    return contract().model_copy(update={"external_ref": ref})


def rows(engine, **where):
    with engine.connect() as conn:
        found = conn.execute(select(R).order_by(R.c.id)).all()
    return [r for r in found if all(getattr(r, k) == v for k, v in where.items())]


def view(r) -> tuple:
    return (r.need_ref, r.evidence, r.kind, r.status)


def test_unique_open_request_per_student_and_fact(engine, clean):
    with engine.begin() as conn:
        plan = conn.execute(insert(models.plans).values(
            tenant_id="pai", source="counsellor", external_ref="j", student_ref="stu-1", contract={},
            contract_sha256="0" * 64).returning(models.plans.c.id)).scalar_one()
    base = dict(tenant_id="pai", student_ref="stu-1", plan_id=plan, kind="provide", need_kind="fact", need_ref="k.a",
                evidence="stated")
    with engine.begin() as conn:
        conn.execute(insert(R).values(**base, status="open"))
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(insert(R).values(**{**base, "evidence": "shown"}, status="open"))
    with engine.begin() as conn:  # a closed row plus a new open one is fine, and another student's is a different fact
        conn.execute(insert(R).values(**base, status="answered"))
        conn.execute(insert(R).values(**{**base, "student_ref": "stu-2"}, status="open"))
        conn.execute(insert(R).values(**{**base, "need_kind": "document"}, status="open"))


def test_sync_opens_a_row_for_each_request_step(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING))
    got = rows(engine)
    assert sorted(view(r) for r in got) == [(OBTAINED, "stated", "provide", "open"), (TOTAL, "stated", "provide", "open")]
    with engine.connect() as conn:
        asks = {t.id: t.instance_key for t in conn.execute(select(models.tasks).where(models.tasks.c.plan_id == ref.plan_id))}
    assert {asks[r.task_id] for r in got} == {f"provide@fact:{OBTAINED}:stated", f"provide@fact:{TOTAL}:stated"}
    assert {(r.plan_id, r.student_ref, r.need_kind) for r in got} == {(ref.plan_id, "stu-1", "fact")}
    assert k.revise(ref.plan_id, "deadline_recompute", compiled(NOTHING)) is None
    assert len(rows(engine)) == 2  # nothing changed: nothing opened twice


@pytest.mark.req("R-18")
def test_level_change_closes_then_opens_in_one_transaction(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING))
    assert k.revise(ref.plan_id, "student_fact_changed", compiled(TYPED)) is not None
    got = {(r.need_ref, r.evidence): r for r in rows(engine)}
    assert got[(OBTAINED, "stated")].status == "answered" and got[(OBTAINED, "stated")].closed_cause == "request_answered"
    assert got[(TOTAL, "stated")].status == "answered"
    assert got[(OBTAINED, "shown")].status == "open"  # the mark sheet is asked next: one open request for the fact
    assert [r.closed_at for r in got.values() if r.status == "open"] == [None]
    assert len([r for r in rows(engine) if r.status == "open"]) == 1
    # the student takes the marks back: the same fact is asked again, as a fresh row
    k.revise(ref.plan_id, "student_fact_changed", compiled(NOTHING))
    assert sorted(view(r) for r in rows(engine) if r.status == "open") == [
        (OBTAINED, "stated", "provide", "open"), (TOTAL, "stated", "provide", "open")]
    assert [view(r) for r in rows(engine, need_ref=OBTAINED, evidence="shown")] == [(OBTAINED, "shown", "provide", "cancelled")]


def test_plan_closed_cancels_its_requests(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING))
    k.close_plan(ref.plan_id, "superseded:9")
    got = rows(engine)
    assert {r.status for r in got} == {"cancelled"} and {r.closed_cause for r in got} == {"plan_closed"}
    assert all(r.closed_at is not None for r in got)
    k.close_plan(ref.plan_id, "superseded:9")  # closing again changes nothing
    assert {r.status for r in rows(engine)} == {"cancelled"}


def test_second_plan_reuses_the_open_row(engine, clean):
    k = kernel(engine)
    a = k.create_plan(contract_of("ext-a"), compiled(NOTHING))
    b = k.create_plan(contract_of("ext-b"), compiled(NOTHING))
    got = rows(engine)
    assert len(got) == 2 and {r.plan_id for r in got} == {a.plan_id}  # B reuses A's rows
    assert store.duplicates(engine, "pai") == []
    with engine.connect() as conn:
        assert [r.id for r in store.for_plan(conn, "pai", b.plan_id)] == [r.id for r in got]  # and shows them
    # A is closed while B still asks for the facts: the rows pass to B, not cancelled
    k.close_plan(a.plan_id, "superseded:b")
    after = rows(engine)
    assert {(r.status, r.plan_id) for r in after} == {("open", b.plan_id)}
    with engine.connect() as conn:
        steps = {t.id: t for t in conn.execute(select(models.tasks).where(models.tasks.c.plan_id == b.plan_id))}
    assert all(steps[r.task_id].plan_id == b.plan_id for r in after)


def test_concurrent_revisions_keep_one_open_row(engine, clean, monkeypatch):
    """Review Focus 2: two plans of one student both open the same request at the same moment."""
    from app.os.kernel import kernel as kernel_module

    barrier = threading.Barrier(2, timeout=10)
    real = kernel_module.request_store.sync

    def together(*args, **kwargs):
        barrier.wait()  # both transactions have their steps and neither has committed
        return real(*args, **kwargs)

    monkeypatch.setattr(kernel_module.request_store, "sync", together)
    errors: list[BaseException] = []

    def make(ref):
        try:
            kernel(engine).create_plan(contract_of(ref), compiled(NOTHING))
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=make, args=(f"ext-{i}",)) for i in range(2)]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    assert errors == []
    assert sorted(view(r) for r in rows(engine)) == [
        (OBTAINED, "stated", "provide", "open"), (TOTAL, "stated", "provide", "open")]
    assert store.duplicates(engine, "pai") == []


@pytest.mark.req("R-20")
def test_result_expected_has_no_row_and_its_provide_step_has_one(engine, clean):
    k = kernel(engine)
    ref = k.create_plan(contract(), compiled(NOTHING, CALENDAR))
    with engine.connect() as conn:
        steps = {t.instance_key: t for t in conn.execute(select(models.tasks).where(models.tasks.c.plan_id == ref.plan_id))}
    assert f"result_expected@fact:{OBTAINED}" in steps  # the draft waits for the result date
    assert not [r for r in rows(engine) if "result_expected" in (r.kind, r.need_ref)]
    asked = {r.need_ref: r for r in rows(engine)}
    assert asked[OBTAINED].kind == "provide" and asked[OBTAINED].status == "open"
    assert steps[f"provide@fact:{OBTAINED}:stated"].id == asked[OBTAINED].task_id
    assert steps[f"provide@fact:{OBTAINED}:stated"].state == "pending"  # behind the result date: not asked yet
    # the student gives it early: the pending step closes as done and so does its row
    k.revise(ref.plan_id, "student_fact_changed", compiled(TYPED, CALENDAR))
    assert [view(r) for r in rows(engine, need_ref=OBTAINED, evidence="stated")] == [(OBTAINED, "stated", "provide", "answered")]


def test_open_for_get_and_recent_answers(engine, clean):
    k = kernel(engine)
    k.create_plan(contract(), compiled(NOTHING))
    opened = store.open_for(engine, "pai", "stu-1")
    assert sorted(r.need_ref for r in opened) == [OBTAINED, TOTAL] and store.open_for(engine, "pai", "stu-2") == []
    assert store.get(engine, "pai", opened[0].id).need_ref == opened[0].need_ref
    assert store.get(engine, "other", opened[0].id) is None and store.get(engine, "pai", 99999) is None
    assert all(r.title and r.due_at for r in opened)  # the step's title and date travel with the row


def test_rows_hold_no_value(engine, clean):
    cols = {c["name"]: c["type"].__class__.__name__ for c in inspect(engine).get_columns("os_student_requests", schema="os")}
    assert not {n for n, t in cols.items() if t in ("JSONB", "JSON", "NUMERIC", "FLOAT", "BYTEA")}
    k = kernel(engine)
    k.create_plan(contract(), compiled(TYPED))
    for r in rows(engine):
        assert {str(v) for v in (r.need_ref, r.evidence, r.kind, r.status)} <= {OBTAINED, TOTAL, "shown", "provide", "open"}


# --- never ticked ---------------------------------------------------------------------------------------------------

def request_task(engine, plan_id) -> int:
    with engine.connect() as conn:
        return conn.execute(select(models.tasks.c.id).where(
            models.tasks.c.plan_id == plan_id, models.tasks.c.template_key == "provide").order_by(models.tasks.c.id)
        ).scalars().first()


@pytest.mark.req("R-18")
def test_request_step_cannot_be_ticked(world, engine):
    from app.os.ports import plan_actions

    world.vault["stu-1"] = facts_of("stu-1", 1)
    plan_id = world.svc.plans.start_plan(gate_contract()).plan_id
    tid = request_task(engine, plan_id)
    assert tid is not None
    for call in (lambda: inbox_actions.complete(world.svc, "stu-1", tid),
                 lambda: plan_actions.complete_step("stu-1", tid)):
        with pytest.raises(StepActionError) as e:
            call()
        assert e.value.code == "answer_required" and e.value.message == texts.text("answer_required")
    with engine.connect() as conn:
        assert conn.execute(select(models.tasks.c.state).where(models.tasks.c.id == tid)).scalar_one() == "waiting_student"


@pytest.mark.req("R-18")
def test_the_inbox_route_refuses_with_409(world, api):
    world.vault["stu-1"] = facts_of("stu-1", 1)
    plan_id = world.svc.plans.start_plan(gate_contract()).plan_id
    tid = request_task(world.engine, plan_id)
    r = api.post(f"/v1/os/inbox/{tid}/complete", json={}, headers=as_student())
    assert r.status_code == 409 and r.json() == {"detail": texts.text("answer_required")}


# --- GET /v1/os/requests ----------------------------------------------------------------------------------------------

def test_get_requests_404_while_gate_off(world, api):
    world.svc.plans.start_plan(gate_contract())  # v1: no requests, and the Vault does not answer
    r = api.get("/v1/os/requests", headers=as_student())
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    assert api.get("/v1/os/requests").status_code == 401


def test_get_requests_lists_own_only(world, api):
    world.vault["stu-1"] = facts_of("stu-1", 1)
    world.vault["stu-2"] = facts_of("stu-2", 1)
    world.svc.plans.start_plan(gate_contract("stu-1"))
    world.svc.plans.start_plan(gate_contract("stu-2"))
    mine = api.get("/v1/os/requests", headers=as_student("stu-1")).json()["requests"]
    theirs = api.get("/v1/os/requests", headers=as_student("stu-2")).json()["requests"]
    assert mine and theirs and not {r["id"] for r in mine} & {r["id"] for r in theirs}
    one = next(r for r in mine if r["need"]["ref"] == "education.intermediate.marks_obtained")
    assert set(one) == {"id", "task_id", "kind", "need", "status", "due_at", "due_tz", "title", "how"}
    assert one["kind"] == "provide" and one["status"] == "open"
    assert one["need"] == {"kind": "fact", "ref": "education.intermediate.marks_obtained", "evidence": "stated"}
    assert one["how"] == texts.text("how_stated") and one["title"] and one["due_at"] and one["due_tz"]
    doc = next(r for r in mine if r["need"]["kind"] == "document")
    assert doc["how"] == texts.text("how_document") and doc["need"]["evidence"] == "shown"
    assert "choices" not in one  # until Task 4
    # another tenant's rows are not seen (tenant isolation at the store)
    assert store.open_for(world.engine, "other-tenant", "stu-1") == []


def test_get_requests_lists_answers_of_the_last_seven_days(world, api):
    from sqlalchemy import update

    world.vault["stu-1"] = facts_of("stu-1", 1)
    world.svc.plans.start_plan(gate_contract())
    first = api.get("/v1/os/requests", headers=as_student()).json()["requests"][0]
    now = datetime.now(timezone.utc)
    with world.engine.begin() as conn:
        conn.execute(update(R).where(R.c.id == first["id"]).values(status="answered", closed_at=now))
    listed = {r["id"]: r for r in api.get("/v1/os/requests", headers=as_student()).json()["requests"]}
    assert listed[first["id"]]["status"] == "answered"
    with world.engine.begin() as conn:
        conn.execute(update(R).where(R.c.id == first["id"]).values(closed_at=now.replace(year=now.year - 1)))
    assert first["id"] not in {r["id"] for r in api.get("/v1/os/requests", headers=as_student()).json()["requests"]}


# --- the sentences ----------------------------------------------------------------------------------------------------

def test_texts_all_approved_and_complete(tmp_path):
    import yaml

    raw = yaml.safe_load(texts.PATH.read_text(encoding="utf-8"))
    assert raw["approved"] is True and raw["version"] == 1
    assert set(raw["texts"]) == set(texts.KEYS)
    assert all(texts.text(k).strip() for k in texts.KEYS)
    for bad in ({**raw, "approved": False}, {**raw, "texts": {k: v for k, v in raw["texts"].items() if k != "how_shown"}}):
        path = tmp_path / "texts.yaml"
        path.write_text(yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(ValueError):
            texts.load(path)
    assert texts.how("provide", "fact", "shown") == texts.text("how_shown")
    assert texts.how("provide", "document", "shown") == texts.text("how_document")
    assert texts.how("which_is_right", "fact", "shown") == texts.text("how_which_is_right")
