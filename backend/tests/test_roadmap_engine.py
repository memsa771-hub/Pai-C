"""The roadmap engine: from the student's education and live paths, which
fields are open, need a step, are not open, or cannot be checked yet. Pure and
deterministic (spec docs/counselor/ROADMAP_ENGINE_SPEC.md §2 and §5)."""

from unittest.mock import patch

from app.journey import JourneyService
from app.memory.student_records import StudentRecordService
from app.pai_c.paths.fields import study_fields
from app.pai_c.possibilities import PossibilityService
from app.pai_c.roadmap.engine import RoadmapEngine, roadmap_policy, student_standing, verdict
from app.pai_c.roadmap.rules import ibcc_percent, rule_for
from scripts.counselor_eval_support import StudentSession


def fsc(group, percent=None, **extra):
    record = {"qualification_name": "fsc", "field_of_study": group, "academic_status": "completed", **extra}
    if percent is not None:
        record["result"] = {"percentage": percent}
    return record


def standing_of(*records):
    return student_standing(list(records))


def status(field_key, *records):
    return verdict(field_key, standing_of(*records)).status


def add_education(student, db, values):
    StudentRecordService(db).apply(student.workspace_id, "education", values, source_type="user_explicit",
                                   claim_origin="student", capture_method="explicit_correction")
    db.commit()


def add_path(student, db, title, field_key=None, *, why="It builds on what you said.", status="suggested",
             source="analyzer"):
    journey = JourneyService(db).ensure_counselor(student.workspace_id)
    row = PossibilityService(db).add(student.workspace_id, journey.id, title=title, why=why,
                                     kind="discovered" if field_key else "student_added",
                                     source=source, status=status)
    row.study_field = {"key": field_key} if field_key else None
    db.commit()
    return row


def field_title(key):
    return study_fields()[key].title


def build_for(education, paths):
    with StudentSession() as student, student.factory() as db:
        for record in education:
            add_education(student, db, record)
        for key in paths:
            add_path(student, db, field_title(key), key)
        return RoadmapEngine(db).build(student.workspace_id)


def by_key(result):
    return {card["field_key"]: card for card in result["fields"]}


# ---- spec §5 scenarios --------------------------------------------------------

def test_pre_eng_78_open():
    result = build_for([fsc("pre_engineering", 78)],
                       ["electrical_engineering", "computer_engineering", "mbbs"])
    cards = by_key(result)
    assert cards["electrical_engineering"]["status"] == "open"
    assert cards["computer_engineering"]["status"] == "open"
    assert cards["mbbs"]["status"] == "not_open"
    electrical = cards["electrical_engineering"]["verdict"]
    rule = rule_for("electrical_engineering")
    assert electrical["years"] == 4 and electrical["min_percent"] == rule.min_percent
    assert [t["name"] for t in electrical["tests"]] == [t.name for t in rule.entry_tests]
    assert electrical["student_percent"] == 78
    assert result["counts"] == {"open": 2, "step": 0, "not_open": 1, "unknown": 0}
    assert [c["status"] for c in result["fields"]] == ["open", "open", "not_open"]
    assert result["chosen"] is None
    line = result["education_line"]
    assert (line["level_label"], [g["label"] for g in line["groups"]], line["percent"]) == \
        ("FSc", ["Pre-Engineering"], 78)


def test_pre_eng_55_step():
    result = verdict("electrical_engineering", standing_of(fsc("pre_engineering", 55)))
    assert result.status == "step"
    assert {"key": "needs_percent", "min": 60, "have": 55} in result.reasons
    assert any(n.kind == "marks" for n in result.needs)
    template = roadmap_policy()["copy"]["needs_percent"]
    assert template.format(min=60, have=55) == "Needs 60%; you have 55%"


def test_pre_med_engineering_step_and_mbbs_open():
    record = fsc("pre_medical", 80)
    for key in ("electrical_engineering", "civil_engineering", "mechanical_engineering"):
        result = verdict(key, standing_of(record))
        assert result.status == "step", key
        assert result.reasons[0]["key"] == "rule_step" and result.reasons[0]["source"].startswith("https://")
        assert any(n.kind == "bridge" for n in result.needs)
    mbbs = verdict("mbbs", standing_of(record))
    assert mbbs.status == "open" and mbbs.years == 5
    assert all("MDCAT" in t["name"] for t in mbbs.tests) and mbbs.tests
    assert verdict("bds", standing_of(record)).years == 4


def test_ics_cs_open_ce_step_mech_not_open():
    record = {"qualification_name": "ics", "academic_status": "completed", "result": {"percentage": 70}}
    assert status("computer_science", record) == "open"
    assert status("computer_engineering", record) == "step"
    assert status("mechanical_engineering", record) == "not_open"


def test_matric_choose_group_step():
    result = verdict("electrical_engineering",
                     standing_of({"qualification_name": "matric", "field_of_study": "science",
                                  "academic_status": "completed"}))
    assert result.status == "step"
    assert result.reasons[0]["key"] == "choose_group"
    assert [g["code"] for g in result.reasons[0]["groups"]] == ["pre_engineering"]
    assert result.reasons[0]["groups"][0]["label"] == "Pre-Engineering"
    assert [n.kind for n in result.needs] == ["group"]


def test_no_marks_open_with_note():
    result = verdict("electrical_engineering", standing_of(fsc("pre_engineering")))
    assert result.status == "open" and result.student_percent is None
    assert {"key": "add_marks", "min": 60} in result.reasons


def test_no_education_not_readable():
    result = build_for([], ["electrical_engineering"])
    assert result["standing"]["readable"] is False
    assert result["education_line"] is None
    [card] = result["fields"]
    assert card["status"] == "unknown" and card["verdict"]["reasons"][0]["key"] == "needs_education"


def test_bachelor_undergrad_only_note():
    result = build_for([{"qualification_name": "bachelor", "field_of_study": "computer_science",
                         "academic_status": "current"}], ["software_engineering", "mbbs"])
    assert {c["status"] for c in result["fields"]} == {"unknown"}
    assert all(c["verdict"]["reasons"][0]["key"] == "undergrad_only" for c in result["fields"])


# ---- review focus ---------------------------------------------------------------

def test_own_path_without_field_is_unknown():
    with StudentSession() as student, student.factory() as db:
        add_education(student, db, fsc("pre_engineering", 78))
        add_path(student, db, field_title("electrical_engineering"), "electrical_engineering")
        add_path(student, db, "Become a pilot", None, why="You said you love flying.", source="student")
        add_path(student, db, field_title("mbbs"), "mbbs", status="dismissed")
        result = RoadmapEngine(db).build(student.workspace_id)
    assert [(c["title"], c["status"]) for c in result["fields"]] == [
        (field_title("electrical_engineering"), "open"), ("Become a pilot", "unknown")]
    own = result["fields"][1]
    assert own["field_key"] is None and own["why"] == "You said you love flying."
    assert own["verdict"]["reasons"] == [{"key": "cannot_check"}]
    assert verdict("not_a_field", standing_of(fsc("pre_engineering"))).status == "unknown"


def test_marks_from_obtained_total():
    record = fsc("pre_engineering", None, result={"marks_obtained": 605, "marks_total": 1100})
    assert standing_of(record).percent == 55.0
    assert verdict("electrical_engineering", standing_of(record)).status == "step"
    # A matric record never supplies the intermediate marks.
    matric = {"qualification_name": "matric", "academic_status": "completed",
              "result": {"percentage": 90}}
    assert standing_of(fsc("pre_engineering"), matric).percent is None


def test_a_level_grades_equivalence():
    record = {"qualification_name": "a_level", "academic_status": "completed",
              "details": {"subjects": ["physics", "chemistry", "mathematics"]},
              "result": {"grade": "A*AB"}}
    standing = standing_of(record)
    assert standing.level == "a_level" and "pre_engineering" in standing.groups
    assert standing.percent == round(ibcc_percent(["A*", "A", "B"]), 1)
    assert verdict("electrical_engineering", standing).status == "open"


def test_engine_makes_no_model_call():
    import app.pai_c.roadmap.engine as engine
    source = open(engine.__file__, encoding="utf-8").read()
    assert "inference" not in source and "chat_completion" not in source
    with patch("app.inference.gateway.complete", side_effect=AssertionError("model called")):
        result = build_for([fsc("pre_medical", 70)], ["mbbs", "electrical_engineering"])
    assert by_key(result)["mbbs"]["status"] == "open"
