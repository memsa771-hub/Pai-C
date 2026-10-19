"""Shared helpers for kernel-level tests: a tiny playbook with one work and two student tasks."""

from datetime import date, datetime, timezone

from app.os.compiler import compile_plan
from app.os.contracts.route_contract import RouteContract
from app.os.kernel import Kernel
from app.os.knowledge import Fact
from app.os.playbooks import Playbook

TODAY = date(2027, 3, 1)
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)


def playbook(version: int = 1, extra_tasks: list[dict] | None = None, title_a: str = "Milestone A") -> Playbook:
    tasks = [
        {"template_key": "a", "task_type": "system.milestone", "title": title_a, "kind": "work"},
        {"template_key": "apply", "task_type": "student.act", "title": "Apply", "kind": "student",
         "inbox_kind": "act", "fan_out": "programme", "anchor": {"fact": "deadline_close"}, "duration_days": 3,
         "depends_on": [{"key": "a"}]},
        {"template_key": "visa", "task_type": "student.act", "title": "Visa", "kind": "student",
         "inbox_kind": "act", "depends_on": [{"key": "apply"}], "duration_days": 10},
    ]
    return Playbook.model_validate({
        "key": "test_route", "version": version, "route": {"origin": "PK", "destination": "IE", "level": "master"},
        "default_timezone": "Europe/Dublin", "tasks": tasks + (extra_tasks or []),
    })


def contract(refs=("p1",), external_ref="ext-1", student_ref="stu-1") -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": external_ref, "student_ref": student_ref,
        "origin_country": "PK", "destination_country": "IE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)],
    })


def facts(refs=("p1",), day="2027-07-15") -> dict:
    return {(r, "deadline_close"): Fact({"date": day}, "q", "https://uni.example", CHECKED, 2027, "confirmed")
            for r in refs}


def draft(pb: Playbook | None = None, refs=("p1",), day="2027-07-15"):
    return compile_plan(contract(refs), pb or playbook(), {}, facts(refs, day), TODAY)


def kernel(engine) -> Kernel:
    return Kernel(engine, "pai", clock=lambda: datetime(2027, 3, 1, 9, 0, tzinfo=timezone.utc))
