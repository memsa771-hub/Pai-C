"""P1-T10 A3 (R-05, R-15): rule 8 reads the stage H list the Counsellor serves. A programme search of a field the
student ruled out (and did not restore) is not served, so it gives no `in_stage_h` finding. Fictional student."""

from datetime import datetime, timezone

import pytest

from app.models import ExecutionRun
from app.pai_c.connect import consistency as cons
from scripts.counselor_eval_support import StudentSession
from tests.test_path_exclusions import add_path, option, setup

pytestmark = [pytest.mark.req("R-05"), pytest.mark.req("R-15")]


def search_run(db, student, path, refs):
    db.add(ExecutionRun(
        workspace_id=student.workspace_id, requested_by="openagents:pai", objective="Find programmes",
        task_type="program_search", status="completed", constraints={"possibility_id": path.id},
        result={"capability_result": {"programs": [{"opportunity_id": r, "title": r} for r in refs]}}))
    db.commit()


def test_stage_h_fields_follow_what_is_served():
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        path = add_path(db, student, journey, "pharm_d")
        search_run(db, student, path, ["uni-a:pharm"])
        ws = student.workspace_id
        assert cons.counsellor_side(db, ws).stage_h_fields == ("pharm_d",)  # nothing is ruled out yet
        option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        side = cons.counsellor_side(db, ws)
        assert "pharm_d" in side.excluded_fields and side.stage_h_fields == ()  # no longer served
        findings = cons.check(side, NS_OS, mode="settled", now=datetime.now(timezone.utc))
        assert [f for f in findings if f.rule == 8 and "in_stage_h" in f.codes] == []


class _Os:
    latest_version = None
    intake_status_by_version: dict = {}
    refusal_by_version: dict = {}
    plans: list = []
    latest_vault_version = 0
    unprocessed_fact_events: list = []
    needed_file_refs: list = []
    duplicate_requests: list = []


NS_OS = _Os()
