"""Slice 1 acceptance (spec §6 tests 1 and 2): the golden test student, and the fake routes run unchanged."""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path

from app.os.api.queries import plan_out
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import Kernel
from app.os.knowledge import SEED_DIR, Fact, SqlKnowledge, load_seed
from app.os.playbooks import PLAYBOOK_DIR, load_playbook, load_playbook_dir
from app.os.runner import default_registry
from app.os.service import PlanService
from app.os.settings import load_settings

GOLDEN = Path(__file__).parent / "golden" / "test_student_plan.json"
FAKE = Path(__file__).parent / "playbooks"
TODAY = date(2027, 2, 1)
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)

TEST_STUDENT = RouteContract.model_validate({
    "contract_version": "1", "source": "self_serve", "external_ref": "test-student-1", "student_ref": "test-student-1",
    "origin_country": "PK", "destination_country": "DE", "level": "master",
    "target_intake": {"term": "winter", "year": 2027},
    "programmes": [
        {"programme_ref": "tu-chemnitz-embedded-systems", "rank": 1},
        {"programme_ref": "ovgu-eeit", "rank": 2},
        {"programme_ref": "btu-artificial-intelligence", "rank": 3},
    ],
})


def _service(engine, books) -> PlanService:
    return PlanService(engine, load_settings({"DATABASE_URL": "x"}), Kernel(engine, "pai"), SqlKnowledge(engine, "pai"),
                       books, today=lambda: TODAY)


def normalised(plan: dict) -> dict:
    """Stable view for the golden file: no database IDs, datetimes as ISO strings in UTC."""
    def task(t: dict) -> dict:
        out = {k: v for k, v in t.items() if k != "id"}
        if out["due_at"] is not None:
            out["due_at"] = out["due_at"].astimezone(timezone.utc).isoformat()
        return out
    return {"status": plan["status"], "revision": plan["revision"],
            "tasks": sorted((task(t) for t in plan["tasks"]), key=lambda t: t["instance_key"])}


def test_germany_playbook_loads_with_registry():
    book = load_playbook(PLAYBOOK_DIR / "germany_master.v1.yaml")
    assert book.require_citations and len(book.tasks) == 21  # Slice 6a added review_pack, 6b review_visa_file
    default_registry().validate([book])


def test_golden_test_student(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    assert load_seed(SEED_DIR / "germany_ws2027.yaml", kb) == 12
    svc = _service(engine, load_playbook_dir())
    ref = svc.start_plan(TEST_STUDENT)
    got = normalised(plan_out(engine, "pai", ref.plan_id))
    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN.parent.mkdir(exist_ok=True)
        GOLDEN.write_text(json.dumps(got, indent=1, sort_keys=True) + "\n")
    assert got == json.loads(GOLDEN.read_text())


def test_golden_dates_follow_the_rules(engine, clean):
    """Spot checks written by hand, independent of the golden file."""
    load_seed(SEED_DIR / "germany_ws2027.yaml", SqlKnowledge(engine, "pai"))
    svc = _service(engine, load_playbook_dir())
    tasks = {t["instance_key"]: t for t in plan_out(engine, "pai", svc.start_plan(TEST_STUDENT).plan_id)["tasks"]}
    apply = tasks["uni_assist_apply@ovgu-eeit"]
    # 15 July 2027 23:59:59 Berlin (CEST, UTC+2) minus the 56-day uni-assist lead time -> 20 May 2027 21:59:59 UTC.
    assert apply["due_at"].astimezone(timezone.utc).isoformat() == "2027-05-20T21:59:59+00:00"
    assert apply["provisional"] and apply["estimated"] and apply["due_tz"] == "Europe/Berlin"
    # The seeded route is uni_assist (unconfirmed): direct_apply is dropped, and the route fact gets checked.
    assert "direct_apply@ovgu-eeit" not in tasks and "confirm_fact@ovgu-eeit:application_route" in tasks
    # Slice 9 Task 11 (F1): the visa date is derived from a semester start; none is seeded, so every programme's is
    # looked for and the visa step waits for it. There is no route-level visa_target_date check any more.
    assert tasks["visa_apply"]["state"] == "blocked" and tasks["visa_apply"]["blocked_reason"] == "fact_missing:semester_start"
    assert {f"confirm_fact@{p.programme_ref}:semester_start" for p in TEST_STUDENT.programmes} <= set(tasks)
    assert not any("visa_target_date" in k for k in tasks)
    assert tasks["choose_programmes"]["state"] == "waiting_student"
    from_facts = {"admission_test", "application_documents", "review_pack", "admission_result"}  # cite the programme's fact
    assert all(t["citations"] for k, t in tasks.items()
               if t["kind"] == "student" and k.split("@")[0] not in from_facts)


def _complete_all(svc: PlanService, engine, student: str, plan_id: int) -> str:
    from app.os.api.queries import inbox_items

    for _ in range(50):
        items = inbox_items(engine, "pai", student)
        if not items:
            break
        for item in items:
            svc.kernel.complete_student_task(item["id"], student, {})
    return plan_out(engine, "pai", plan_id)["status"]


def test_fake_routes_run_unchanged(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    kb.upsert("programme", "tcd", "deadline_close", Fact({"date": "2027-06-30"}, "Apply by 30 June",
                                                        "https://uni.example/ie", CHECKED, 2027, "confirmed"))
    kb.upsert("programme", "nust", "merit_list_date", Fact({"date": "2027-08-15"}, "Merit list on 15 August",
                                                          "https://uni.example/pk", CHECKED, 2027, "confirmed"))
    svc = _service(engine, load_playbook_dir(FAKE))
    for student, dest, level, ref in (("ie-1", "IE", "master", "tcd"), ("pk-1", "PK", "bachelor", "nust")):
        contract = RouteContract.model_validate({
            "contract_version": "1", "source": "self_serve", "external_ref": student, "student_ref": student,
            "origin_country": "PK", "destination_country": dest, "level": level,
            "target_intake": {"term": "winter", "year": 2027}, "programmes": [{"programme_ref": ref, "rank": 1}],
        })
        plan = svc.start_plan(contract)
        assert _complete_all(svc, engine, student, plan.plan_id) == "done"
