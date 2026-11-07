"""P1-T10 (R-05, R-15): rule 8 reads the stage H list the Counsellor really serves, and a restored path is not excluded.
Fictional student."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from app.models import ExecutionRun
from app.pai_c.connect import consistency as cons
from app.pai_c.connect import places
from app.pai_c.paths import exclusions
from app.pai_c.possibilities import PossibilityService
from scripts.counselor_eval_support import StudentSession
from tests.test_path_exclusions import add_path, option, setup

pytestmark = [pytest.mark.req("R-05"), pytest.mark.req("R-15")]


class _Os:
    latest_version = None
    intake_status_by_version: dict = {}
    refusal_by_version: dict = {}
    plans: list = []
    latest_vault_version = 0
    unprocessed_fact_events: list = []
    needed_file_refs: list = []
    duplicate_requests: list = []


def search_run(db, student, path, refs):
    db.add(ExecutionRun(
        workspace_id=student.workspace_id, requested_by="openagents:pai", objective="Find programmes",
        task_type="program_search", status="completed", constraints={"possibility_id": path.id},
        result={"capability_result": {"programs": [{"opportunity_id": r, "title": r} for r in refs]}}))
    db.commit()


def fresh(db, workspace_id, result, facts):
    """The freshness recheck needs researched sources; these tests are about exclusions, so every programme is fresh."""
    return result, False


@pytest.fixture(autouse=True)
def _fresh_programmes():
    with patch("app.pai_c.paths.programs.current_programs", fresh):
        yield


def rule8(side):
    return [f for f in cons.check(side, _Os(), mode="settled", now=datetime.now(timezone.utc)) if f.rule == 8]


def test_a_search_of_a_ruled_out_field_is_not_served_and_gives_no_finding():
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        path = add_path(db, student, journey, "pharm_d")
        search_run(db, student, path, ["uni-a:pharm"])
        ws = student.workspace_id
        assert cons.counsellor_side(db, ws).stage_h_fields == ("pharm_d",)  # served while nothing is ruled out
        option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        exclusions.apply_exclusions(db, ws)
        db.commit()
        side = cons.counsellor_side(db, ws)
        assert side.excluded_fields == ("pharm_d",) and side.stage_h_fields == ()
        assert rule8(side) == []


def test_a_restored_path_is_no_longer_excluded_and_gives_no_finding():
    """The Vault option stays ruled out after the student restores the path ("save"); the field is theirs again."""
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        path = add_path(db, student, journey, "pharm_d")
        option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        exclusions.apply_exclusions(db, student.workspace_id)
        db.commit()
        restored, _ = PossibilityService(db).transition(student.workspace_id, path.id, "save")
        db.commit()
        search_run(db, student, restored, ["uni-a:pharm"])
        side = cons.counsellor_side(db, student.workspace_id)
        assert "pharm_d" in exclusions.excluded_fields(db, student.workspace_id)  # the option itself is still there
        assert side.excluded_fields == () and side.stage_h_fields == ("pharm_d",)
        assert rule8(side) == []  # no finding every night for a student's own choice


def test_a_leaked_programme_of_a_truly_excluded_field_is_a_finding():
    """The check reads the served list itself: if the reader's filter broke, the leak would show."""
    with StudentSession() as student, student.factory() as db:
        turn, journey = setup(student, db)
        path = add_path(db, student, journey, "pharm_d")
        option(db, student, "Pharm-D", quote="Pharm-D nahi karni")
        exclusions.apply_exclusions(db, student.workspace_id)
        db.commit()
        search_run(db, student, path, ["uni-a:pharm"])
        with patch.object(places, "run_is_served", lambda *a, **k: True):  # the reader's filter is broken
            side = cons.counsellor_side(db, student.workspace_id)
        assert side.stage_h_fields == ("pharm_d",)
        got = rule8(side)
        assert [(f.rule, f.codes) for f in got] == [(8, ("in_stage_h",))]
