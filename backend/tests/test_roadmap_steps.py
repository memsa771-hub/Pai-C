"""Every step of a route coloured from the Vault (FOUR_FEATURES_SPEC.md §4.1):
done / half / not, with the Vault entry behind it and the admission rule.
Pure: Vault view rows are built here, today is frozen."""

from dataclasses import asdict
from datetime import date
from types import SimpleNamespace

from app.pai_c.paths.fields import study_fields
from app.pai_c.roadmap.decisions import done_keys
from app.pai_c.roadmap.engine import roadmap_policy, student_standing, verdict
from app.pai_c.roadmap.rules import rule_for
from app.pai_c.roadmap.steps import route_steps

TODAY = date(2026, 10, 29)


def fsc(group, percent=None, status="completed", **extra):
    record = {"qualification_name": "fsc", "field_of_study": group, "academic_status": status, **extra}
    if percent is not None:
        record["result"] = {"percentage": percent}
    return record


def row(kind, value, id="1", level="stated", capture="vault_api", source="user_explicit", document=None):
    entry = {"kind": "record", "type": kind, "id": id, "value": value, "level": level, "source": source,
             "document": document}
    return SimpleNamespace(entry=entry, capture=capture, sensitivity="normal")


def route(field_key, education=None, *others, steps_done=()):
    rows = ([row("education", education, id="edu")] if education else []) + list(others)
    standing = student_standing([education] if education else [])
    card = {"field_key": field_key, "title": study_fields()[field_key].title,
            "verdict": asdict(verdict(field_key, standing))}
    return route_steps(card, standing, rows, today=TODAY, steps_done=steps_done)


def step(steps, key):
    return next(s for s in steps if s["key"] == key or s["kind"] == key)


def test_route_in_order_with_copy_keys():
    steps = route("electrical_engineering", fsc("pre_engineering", 78))
    assert [s["kind"] for s in steps] == ["group", "complete_intermediate", "marks", "test", "apply", "degree"]
    copy = roadmap_policy()["copy"]
    for s in steps:
        assert s["label_key"] in copy and s["status"] in {"done", "half", "not"}
        assert s["colour"] == roadmap_policy()["steps"]["colours"][s["status"]]
    assert step(steps, "degree")["values"]["years"] == 4


def test_group_done_from_education():
    steps = route("electrical_engineering", fsc("pre_engineering", 78))
    group = step(steps, "group")
    assert group["status"] == "done" and group["colour"] == "green"
    assert group["evidence"] == {"id": "education:edu", "level": "stated", "source_label": "Details"}
    rule = rule_for("electrical_engineering")
    assert group["rule"] == {"source": rule.sources[0], "confidence": rule.confidence}
    assert step(steps, "complete_intermediate")["status"] == "done"


def test_matric_group_step_not():
    matric = {"qualification_name": "matric", "academic_status": "current"}
    steps = route("electrical_engineering", matric)
    group = step(steps, "group")
    assert group["status"] == "not" and group["label_key"] == "step_group"
    assert [g["route_label"] for g in group["values"]["groups"]] == ["FSc Pre-Engineering"]
    assert step(steps, "complete_intermediate")["status"] == "not"
    assert step(steps, "marks")["status"] == "not"  # no intermediate marks exist yet


def test_marks_done_intermediate_half():
    """A current FSc student with Part-1 marks above the floor: marks done,
    intermediate half with the Part-2 exam month from the calendar."""
    steps = route("electrical_engineering", fsc("pre_engineering", 72, status="current"))
    assert step(steps, "marks")["status"] == "done"
    finish = step(steps, "complete_intermediate")
    assert finish["status"] == "half" and finish["colour"] == "yellow"
    assert finish["label_key"] == "step_finish_exam"
    assert finish["values"]["month"] == "May" and finish["values"]["year"] == 2027
    assert finish["evidence"]["id"] == "education:edu"


def test_marks_below_floor_not():
    marks = step(route("electrical_engineering", fsc("pre_engineering", 55)), "marks")
    assert marks["status"] == "not" and marks["values"] == {"min": 60, "have": 55}
    assert marks["evidence"]["id"] == "education:edu"


def test_marks_unknown_half():
    marks = step(route("electrical_engineering", fsc("pre_engineering")), "marks")
    assert marks["status"] == "half" and marks["label_key"] == "step_marks_unknown"


def test_test_attempt_registered_half_passed_done():
    name = rule_for("mbbs").tests_for("mbbs")[0].name
    none = route("mbbs", fsc("pre_medical", 80))
    assert step(none, "test")["status"] == "not" and step(none, "test")["evidence"] is None
    registered = row("test_attempt", {"test_type": "MDCAT", "details": {"status": "registered"}}, id="t1")
    half = step(route("mbbs", fsc("pre_medical", 80), registered), "test")
    assert half["key"] == f"test:{name}" and half["status"] == "half"
    assert half["evidence"]["id"] == "test_attempt:t1"
    below = row("test_attempt", {"test_type": "mdcat", "overall_score": "40"}, id="t2")
    assert step(route("mbbs", fsc("pre_medical", 80), below), "test")["status"] == "half"
    passed = row("test_attempt", {"test_type": "mdcat", "overall_score": "160/200"}, id="t3", level="shown",
                 source="document", document={"filename": "mdcat-result.pdf"})
    done = step(route("mbbs", fsc("pre_medical", 80), below, passed), "test")
    assert done["status"] == "done"
    assert done["evidence"] == {"id": "test_attempt:t3", "level": "shown", "source_label": "mdcat-result.pdf"}
    # Another test's attempt proves nothing here.
    ecat = row("test_attempt", {"test_type": "ecat", "overall_score": "90"}, id="t4")
    assert step(route("mbbs", fsc("pre_medical", 80), ecat), "test")["status"] == "not"


def test_apply_manual_only():
    steps = route("electrical_engineering", fsc("pre_engineering", 78))
    assert step(steps, "apply")["status"] == "not" and step(steps, "apply")["evidence"] is None
    assert step(steps, "degree")["status"] == "not"
    ticked = route("electrical_engineering", fsc("pre_engineering", 78), steps_done=["apply"])
    apply = step(ticked, "apply")
    assert apply["status"] == "done" and apply["manual_done"] is True
    assert apply["evidence"] == {"id": None, "level": "stated",
                                 "source_label": roadmap_policy()["copy"]["marked_by_you"]}
    # A tick on a step the Vault proves is ignored; the Vault entry stands.
    group = step(route("electrical_engineering", fsc("pre_engineering", 78), steps_done=["group"]), "group")
    assert group["manual_done"] is False and group["evidence"]["id"] == "education:edu"


def test_bridge_done_with_course_record():
    """Pre-Medical into Computer Science needs deficiency mathematics; a course
    record for it turns the bridge green."""
    steps = route("computer_science", fsc("pre_medical", 70))
    bridge = step(steps, "bridge")
    assert bridge["status"] == "not" and bridge["label_key"] == "step_bridge"
    assert bridge["rule"]["source"] and step(steps, "group")["status"] == "half"
    course = row("course", {"education_id": "edu", "name": "Deficiency Mathematics"}, id="c1")
    bridge = step(route("computer_science", fsc("pre_medical", 70), course), "bridge")
    assert bridge["status"] == "done" and bridge["evidence"]["id"] == "course:c1"
    biology = row("course", {"education_id": "edu", "name": "Biology"}, id="c2")
    assert step(route("computer_science", fsc("pre_medical", 70), biology), "bridge")["status"] == "not"


def test_legacy_ticks_map_by_position_once():
    old = SimpleNamespace(steps=[{"key": "step_marks", "min": 60, "have": 55},
                                 {"key": "step_test", "name": "MDCAT (MBBS)"},
                                 {"key": "step_apply", "degree": "MBBS"}],
                          steps_done=[True, False, True])
    assert done_keys(old) == ["marks", "apply"]
    assert done_keys(SimpleNamespace(steps=[], steps_done=["apply"])) == ["apply"]


def test_degree_student_has_no_undergraduate_route():
    bachelor = {"qualification_name": "bachelor", "field_of_study": "computer_science",
                "academic_status": "current"}
    assert route("electrical_engineering", bachelor) == []


def test_tickable_only_where_the_vault_is_silent():
    """A tick is a claim the student makes; it is offered only on applying and
    on steps the Vault cannot observe yet (a bridge or check with no course, a
    test with no attempt). Never where the Vault already says something."""
    steps = route("electrical_engineering", fsc("pre_engineering", 78))
    assert {s["kind"]: s["tickable"] for s in steps} == {
        "group": False, "complete_intermediate": False, "marks": False, "test": True, "apply": True, "degree": False}
    # Marks below the floor are contradicted by the record: no tick.
    assert step(route("electrical_engineering", fsc("pre_engineering", 55)), "marks")["tickable"] is False
    # A registered test is under way in the Vault: no tick.
    registered = row("test_attempt", {"test_type": "MDCAT", "details": {"status": "registered"}}, id="t1")
    assert step(route("mbbs", fsc("pre_medical", 80), registered), "test")["tickable"] is False
    # A bridge with no course is unobserved; a course record proves it.
    assert step(route("computer_science", fsc("pre_medical", 70)), "bridge")["tickable"] is True
    course = row("course", {"education_id": "edu", "name": "Deficiency Mathematics"}, id="c1")
    assert step(route("computer_science", fsc("pre_medical", 70), course), "bridge")["tickable"] is False
    assert set(roadmap_policy()["steps"]["tickable_kinds"]) == {"apply", "bridge", "check", "test"}


def test_tick_is_ignored_where_the_vault_speaks():
    """A stored tick on a step the Vault observes (older data, or a step that
    became observed later) changes nothing; the Vault's colour stands."""
    name = rule_for("mbbs").tests_for("mbbs")[0].name
    registered = row("test_attempt", {"test_type": "mdcat", "details": {"status": "registered"}}, id="t1",
                     level="shown", source="document", document={"filename": "mdcat-slip.pdf"})
    half = step(route("mbbs", fsc("pre_medical", 80), registered, steps_done=[f"test:{name}"]), "test")
    assert half["status"] == "half" and half["manual_done"] is False
    assert half["evidence"] == {"id": "test_attempt:t1", "level": "shown", "source_label": "mdcat-slip.pdf"}
    low = step(route("electrical_engineering", fsc("pre_engineering", 55), steps_done=["marks"]), "marks")
    assert low["status"] == "not" and low["manual_done"] is False
    # A ticked unobserved test is done "as you marked it" and stays tickable, so it can be unticked.
    ticked = step(route("mbbs", fsc("pre_medical", 80), steps_done=[f"test:{name}"]), "test")
    assert ticked["status"] == "done" and ticked["manual_done"] is True and ticked["tickable"] is True


def test_steps_follow_the_standings_record():
    """Two education records: an older current FSc and a completed Matric edited
    later. The standing reads the current FSc; the steps cite that same record."""
    from app.pai_c.memory import MemoryService
    from app.pai_c.roadmap.engine import RoadmapEngine
    from scripts.counselor_eval_support import StudentSession
    from tests.test_roadmap_engine import add_education, add_path, field_title
    with StudentSession() as student, student.factory() as db:
        add_education(student, db, fsc("pre_engineering", 72, status="current"))
        add_education(student, db, {"qualification_name": "matric", "academic_status": "completed",
                                    "result": {"percentage": 90}})
        add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        page = RoadmapEngine(db).build(student.workspace_id, today=TODAY)
        cards = [c for c in MemoryService(db).profile_cards(student.workspace_id) if c["kind"] == "education"]
    fsc_id = next(c["id"] for c in cards if c["value"]["qualification_name"] == "fsc")
    assert page["standing"]["level"] == "fsc"
    steps = page["fields"][0]["steps"]
    for key in ("group", "complete_intermediate", "marks"):
        assert step(steps, key)["evidence"]["id"] == f"education:{fsc_id}", key
    assert step(steps, "complete_intermediate")["status"] == "half"
