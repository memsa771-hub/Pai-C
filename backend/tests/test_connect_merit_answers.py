"""P2 freeze exception 2 (R-48): with CONNECT_MERIT_ANSWERS on, the chosen field's path carries merit items built in
code from PAI OS MeritCheck; with it off, the path analyzer is unchanged. Fictional students and fake models only."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app import pai_os_bridge
from app.config import config
from app.models import BackgroundJob
from app.pai_c.connect import merit
from app.pai_c.paths.analyzer import enqueue_path_analysis, path_analysis_job
from app.pai_c.possibilities import PossibilityService
from scripts.counselor_eval_support import StudentSession
from tests.counselor_fixtures import fake_post
from tests.test_path_analyzer import STRONG, VAULT_ITEM, add_education, analysis, fit, path, seed, title

pytestmark = pytest.mark.req("R-48")

SOURCE = {"url": "https://admissions.example.test/merit", "quote": "Aggregate = 50% part one + 50% part two",
          "checked_at": "2026-11-01T00:00:00Z"}
FORMULA = {"parts": [{"name": "part_one", "marks_part": "marks.a", "weight": 0.5},
                     {"name": "part_two", "marks_part": "marks.b", "weight": 0.5}],
           "total": 100.0, "owner_ref": None, "level": "verified", "source": SOURCE}


def check(status, **extra):
    base = {"schema": "pai.merit_check.v1", "student_ref": "s", "programme_ref": "p1",
            "intake": {"term": "fall", "year": 2027}, "category": None, "status": status, "formula": None,
            "aggregate": None, "marks_used": [], "parts": [], "closing_merits": []}
    return base | extra


CLOSING = [
    {"intake": {"term": "fall", "year": 2026}, "value": 88.5, "list_number": None, "list_complete": True,
     "level": "verified", "source": SOURCE},
    {"intake": {"term": "unrecorded", "year": 2025}, "value": 86.25, "list_number": 3, "list_complete": False,
     "level": "verified", "source": SOURCE},
    {"intake": {"term": "fall", "year": 2024}, "value": None, "list_number": None, "list_complete": True,
     "level": "not_confirmed", "source": SOURCE},
]


def test_a_computed_merit_names_its_number_its_weakest_evidence_and_never_a_chance():
    note = merit.note_for(check("computed", formula=FORMULA, aggregate=81.4,
                                marks_used=[{"key": "marks.a", "value": 800, "out_of": 1100, "evidence": "shown"},
                                            {"key": "marks.b", "value": 900, "out_of": 1100, "evidence": "stated"}],
                                parts=[{"name": "part_one", "status": "known"}, {"name": "part_two", "status": "known"}],
                                closing_merits=CLOSING))
    assert "81.4 out of 100" in note
    assert "marks you told PAI" in note  # the weakest evidence (stated) is said, never shown as firm (T10 M5)
    assert "Closing merit (fall 2026): 88.5." in note
    assert "Lowest merit on list 3 (term not recorded 2025): 86.25." in note  # not complete: never "the closing merit"
    assert "Closing merit (fall 2024): not confirmed." in note  # no value travels below verified
    assert note.endswith("This is not a chance of admission.")


def test_missing_and_not_confirmed_say_why_and_carry_no_number():
    missing = merit.note_for(check("missing", formula=FORMULA, parts=[{"name": "part_one", "status": "known"},
                                                                      {"name": "part_two", "status": "missing"}]))
    assert "your part two marks are missing" in missing
    marks = merit.note_for(check("not_confirmed", formula=FORMULA, parts=[{"name": "part_one", "status": "not_confirmed"}]))
    assert "do not add up" in marks
    no_formula = merit.note_for(check("not_confirmed"))
    assert "formula for this place is not confirmed" in no_formula
    for note in (missing, marks, no_formula):
        assert not any(ch.isdigit() for ch in note)


def test_off_returns_the_same_paths_and_never_asks_pai_os():
    paths = [{"title": "EE", "fit": [], "study_field": {"key": "electrical_engineering"}}]
    with patch.object(config, "CONNECT_MERIT_ANSWERS", False), \
         patch.object(pai_os_bridge, "merit_check", side_effect=AssertionError("asked")):
        assert merit.attach(None, "ws", paths) is paths


def test_on_adds_items_only_to_the_chosen_field_and_replaces_older_ones():
    item = {"label": "Merit for X", "status": "unknown", "note": "n", "evidence": [], "source": merit.SOURCE}
    paths = [{"title": "EE", "fit": [{"label": "old", "source": merit.SOURCE}, {"label": "Skill"}],
              "study_field": {"key": "electrical_engineering"}},
             {"title": "CE", "fit": [{"label": "Skill"}], "study_field": {"key": "civil_engineering"}}]
    with patch.object(merit, "part_on", return_value=True), \
         patch.object(merit, "fit_items", return_value=("electrical_engineering", [item])):
        out = merit.attach(None, "ws", paths)
    assert out[0]["fit"] == [{"label": "Skill"}, item]
    assert out[1] is paths[1]
    with patch.object(merit, "part_on", return_value=True), \
         patch.object(merit, "fit_items", side_effect=RuntimeError("down")):
        assert merit.attach(None, "ws", paths) is paths  # a failure never stops the path run


def test_fit_items_follow_the_chosen_places_in_rank_order():
    row = SimpleNamespace(field_key="electrical_engineering", destination_country="XX", level="bachelor",
                          intake={"term": "fall", "year": 2027},
                          places=[{"programme_ref": "p2", "rank": 2}, {"programme_ref": "p1", "rank": 1}])
    asked = []

    def fake_check(student_ref, ref, term, year):
        asked.append((ref, term, year))
        return check("not_confirmed")

    with patch("app.pai_c.roadmap.decisions.RouteDecisionService.active", return_value=row), \
         patch.object(pai_os_bridge, "merit_check", side_effect=fake_check), \
         patch("app.pai_c.connect.places.places_for", return_value=[{"ref": "p1", "name": "Place One"}]):
        field, items = merit.fit_items(None, "ws")
    assert field == "electrical_engineering" and asked == [("p1", "fall", 2027), ("p2", "fall", 2027)]
    assert [i["label"] for i in items] == ["Merit for Place One", "Merit for your choice 2"]
    assert all(i["status"] == "unknown" and i["source"] == merit.SOURCE for i in items)
    with patch("app.pai_c.roadmap.decisions.RouteDecisionService.active", return_value=None):
        assert merit.fit_items(None, "ws") is None


async def _run(flag_on: bool, item: dict) -> list:
    """One analyzer run on a fictional student with a recorded model reply; returns the stored fit of the EE path."""
    with StudentSession() as student, student.factory() as db:
        turn, _, _ = seed(student, db)
        add_education(student, db)
        job_id = enqueue_path_analysis(db, student.workspace_id, source_event_id=turn.source_event_id,
                                       channel=turn.channel, reason="asked")
        db.commit()
        recorded = json.dumps(analysis(path("electrical_engineering", ids=["c3", VAULT_ITEM],
                                            fits=[*STRONG, fit("Afford fees", "blocker", ["c2"])])))
        with patch("app.pai_c.paths.analyzer.chat_completion", AsyncMock(return_value=recorded)), \
             patch("app.pai_c.paths.analyzer.send_to_student", AsyncMock(side_effect=fake_post(student))), \
             patch.object(config, "CONNECT_MERIT_ANSWERS", flag_on), \
             patch.object(merit, "part_on", return_value=flag_on), \
             patch.object(merit, "fit_items", return_value=("electrical_engineering", [item])):
            result = await path_analysis_job(db.get(BackgroundJob, job_id), db)
        assert result["status"] == "posted"
        db.expire_all()
        rows = {row.title: row for row in PossibilityService(db).list(student.workspace_id)}
        return rows[title("electrical_engineering")].fit


@pytest.mark.asyncio
async def test_replay_off_and_on_differ_only_by_the_merit_item():
    item = {"label": "Merit for Place One", "status": "unknown", "evidence": [], "source": merit.SOURCE,
            "note": merit.note_for(check("computed", formula=FORMULA, aggregate=81.4,
                                         marks_used=[{"key": "marks.a", "value": 800, "out_of": 1100,
                                                      "evidence": "shown"}],
                                         parts=[{"name": "part_one", "status": "known"}]))}
    off = await _run(False, item)
    on = await _run(True, item)
    assert item not in off
    assert on == off + [item]
