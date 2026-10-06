"""Versioned Counselor slot ordering, applicability and answer precedence."""

from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.counseling.slots import CounselorSlotRegistry, next_open_slot, resolve_slot_states
from app.database import Base
from app.memory.education_journey import canonical_education_level, education_group
from app.memory.student_snapshot import StudentSnapshot
from app.models import CounselorSlotAnswer, EventRecord, ProfileRequirement


@compiles(JSONB, "sqlite")
def _sqlite_jsonb(type_, compiler, **kw):
    return "JSON"


def snapshot(*, facts=None, records=None):
    return StudentSnapshot("student", facts or {}, records or {}, (), datetime.now(timezone.utc))


def slot(key, stage, priority, source_type="vault_fact", source_key=None,
         source_path=None, applicability=None):
    return ProfileRequirement(key=f"discovery.{key}", stage=stage, priority=priority,
                              tier="important", source_type=source_type,
                              source_key=source_key or key, source_path=source_path,
                              selector="any", applicability=applicability or {},
                              question="?", accepts_unknown=True, version=1)


def test_canonical_qualification_names_fill_level_without_reasking():
    for name, expected in (("FSc Pre-Engineering", "upper_secondary"),
                           ("A-Levels", "upper_secondary"),
                           ("BS Computer Science", "bachelor"),
                           ("MSc Physics", "master")):
        assert canonical_education_level(None, name) == expected
    assert education_group(None, "FSc Pre-Medical") == "pre_university"
    assert canonical_education_level("bachelor", "FSc") == "bachelor"
    assert canonical_education_level(None, "something unfamiliar") is None


def test_canonical_fact_wins_and_recent_pending_prevents_repeat():
    rows = [slot("budget", "direction", 50, source_key="finance.budget"),
            slot("timing", "direction", 40), slot("field_interest", "direction", 30)]
    student = snapshot(facts={"finance.budget": {"value": "15 lakh"}})
    states = resolve_slot_states(rows, student,
        pending={"budget": ("pending", "10 lakh"), "timing": ("pending", "next year")})
    assert states["budget"].value == "15 lakh"
    assert states["budget"].status == "answered"
    assert next_open_slot(rows, states, student, "direction").key == "discovery.field_interest"


def test_unknown_and_declined_are_answered_but_empty_pending_is_not():
    rows = [slot("budget", "direction", 50), slot("timing", "direction", 40)]
    student = snapshot()
    states = resolve_slot_states(rows, student, responses={"discovery.budget": "declined"},
                                 pending={"timing": ("valid_unknown", None)})
    assert all(state.answered for state in states.values())
    assert next_open_slot(rows, states, student, "direction") is None


def test_goal_reason_immediately_after_goal_and_subjects_if_no_goal():
    rows = [slot("stated_goal", "direction", 100),
            slot("goal_reason", "direction", 95, applicability={"slot_value": "stated_goal"}),
            slot("subject_likes", "direction", 90, applicability={"slot_missing": "stated_goal"}),
            slot("budget", "direction", 50)]
    student = snapshot()
    states = resolve_slot_states(rows, student)
    assert next_open_slot(rows, states, student, "direction").key == "discovery.stated_goal"
    states = resolve_slot_states(rows, student, pending={"stated_goal": ("pending", "MS in Germany")})
    assert next_open_slot(rows, states, student, "direction").key == "discovery.goal_reason"
    states = resolve_slot_states(rows, student, pending={"stated_goal": ("valid_unknown", None)})
    assert next_open_slot(rows, states, student, "direction").key == "discovery.subject_likes"


def test_conditional_family_and_work_slots():
    rows = [slot("family_wish", "direction", 60, source_type="record_field",
                 source_key="external_influence", source_path="suggested_direction",
                 applicability={"family_mentioned": True}),
            slot("study_mode", "direction", 50, applicability={"working_now": True}),
            slot("budget", "direction", 40)]
    student = snapshot()
    states = resolve_slot_states(rows, student)
    assert next_open_slot(rows, states, student, "direction").key == "discovery.budget"
    student = snapshot(records={"external_influence": [{"influencer_type": "friend",
                                                         "suggested_direction": "engineering"}]})
    states = resolve_slot_states(rows, student)
    assert next_open_slot(rows, states, student, "direction").key == "discovery.budget"
    student = snapshot(records={"external_influence": [{"influencer_type": "parent",
                                                         "suggested_direction": "engineering"}]})
    states = resolve_slot_states(rows, student)
    assert next_open_slot(rows, states, student, "direction").key == "discovery.budget"
    # The family slot itself is answered by the accepted influence record.
    assert states["family_wish"].answered
    student = snapshot(records={"work_experience": [{"role": "bank operations"}]})
    states = resolve_slot_states(rows, student)
    assert next_open_slot(rows, states, student, "direction").key == "discovery.study_mode"
    student = snapshot(facts={"identity.status_category": {"value": "professional"}})
    states = resolve_slot_states(rows, student)
    assert next_open_slot(rows, states, student, "direction").key == "discovery.study_mode"


def test_pending_window_uses_five_student_turns_not_five_slot_rows():
    workspace = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[EventRecord.__table__, CounselorSlotAnswer.__table__])
    try:
        with Session(engine) as db:
            for number in range(6):
                event_id = f"turn-{number}"
                db.add(EventRecord(id=event_id, network_id=workspace, type="workspace.message.posted",
                                   source="human:student", target="channel/pai-counselor",
                                   payload={"content": "answer"}, timestamp=number))
                db.add(CounselorSlotAnswer(workspace_id=workspace, source_event_id=event_id,
                                            slot_key=f"slot-{number}", value=f"answer-{number}"))
                if number in {1, 5}:
                    db.add(CounselorSlotAnswer(workspace_id=workspace, source_event_id=event_id,
                                                slot_key="shared", value=f"answer-{number}"))
            db.commit()
            recent = CounselorSlotRegistry(db).pending_recent(workspace)
            assert "slot-0" not in recent
            assert len(recent) == 6
            assert recent["slot-5"] == ("pending", "answer-5")
            assert recent["shared"] == ("pending", "answer-5")
    finally:
        engine.dispose()
