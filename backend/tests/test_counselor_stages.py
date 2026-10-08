"""Goal discovery and Counselor stage transitions stay server owned."""

from itertools import product

import pytest
from sqlalchemy import select

from app.counseling.stages import (CHOSEN, DIRECTION, FOUNDATION, IDENTITY,
                                   PROPOSED, RESEARCHING, TRANSITIONS,
                                   advance_discovery_stage,
                                   require_counselor_transition)
from app.journey import JourneyError, JourneyService
from app.memory.candidates import MemoryCandidateService
from app.memory.reconciler import MemoryReconciler
from app.memory.profile_requirements import ProfileRequirementRegistry
from app.memory.student_snapshot import StudentSnapshotService
from app.models import ProfileRequirement, StudentGoal, StudentJourneyEvent
from scripts.counselor_eval_support import StudentSession


@pytest.mark.parametrize("current,target", list(product(TRANSITIONS, TRANSITIONS)))
def test_every_counselor_transition_is_explicit(current, target):
    allowed = current == target or target in TRANSITIONS[current]
    if target == CHOSEN:
        allowed = current == target
    if current == CHOSEN and target == DIRECTION:
        allowed = False
    if allowed:
        assert require_counselor_transition(current, target) == target
    else:
        with pytest.raises(ValueError):
            require_counselor_transition(current, target)


def test_chosen_requires_server_validated_student_choice():
    assert require_counselor_transition(PROPOSED, CHOSEN,
                                        validated_choice=True) == CHOSEN
    with pytest.raises(ValueError):
        require_counselor_transition(DIRECTION, CHOSEN,
                                     validated_choice=True)


def test_chosen_replanning_requires_explicit_escalation():
    with pytest.raises(ValueError):
        require_counselor_transition(CHOSEN, DIRECTION)
    assert require_counselor_transition(
        CHOSEN, DIRECTION, replan_escalation=True) == DIRECTION


def test_counselor_journey_starts_without_an_active_goal_and_rejects_generic_stage_edits():
    with StudentSession() as student, student.factory() as db:
        service = JourneyService(db)
        first = service.ensure_counselor(student.workspace_id)
        assert first.current_stage == IDENTITY and first.active_goal is None
        assert service.ensure_counselor(student.workspace_id).id == first.id
        with pytest.raises(JourneyError):
            service.set_stage(student.workspace_id, first.id, "COMPLETED")
        with pytest.raises(JourneyError):
            service.update(student.workspace_id, first.id, current_stage="CHOSEN")
        foundation = service.set_counselor_stage(student.workspace_id, first.id, FOUNDATION)
        assert foundation.current_stage == FOUNDATION
        assert db.execute(select(StudentJourneyEvent).where(
            StudentJourneyEvent.journey_id == first.id)).scalars().all()


def test_multiturn_goal_details_reconcile_to_one_student_reported_goal():
    with StudentSession() as student, student.factory() as db:
        candidates = MemoryCandidateService(db)
        first = candidates.propose(
            student.workspace_id, "student_record", key="goal", confidence=0.95,
            source_type="conversation", evidence={"quote": "I want CS in USA"},
            proposed_value={"goal_type": "education", "title": "CS in USA",
                            "details": {"stated_preference": "CS in USA"}})
        assert MemoryReconciler(db).reconcile(first).accepted
        goal = db.execute(select(StudentGoal).where(
            StudentGoal.workspace_id == student.workspace_id)).scalar_one()
        later = candidates.propose(
            student.workspace_id, "student_record", key="goal", confidence=0.95,
            source_type="conversation",
            entities={"record_id": goal.id},
            evidence={"quote": "My parents want me abroad; I want a tech job"},
            proposed_value={"details": {
                "underlying_objective": "an international tech career",
                "drivers": ["family", "career"], "constraints": []}})
        assert MemoryReconciler(db).reconcile(later).accepted
        db.commit()
        rows = db.execute(select(StudentGoal).where(
            StudentGoal.workspace_id == student.workspace_id)).scalars().all()
        assert len(rows) == 1
        assert rows[0].details == {
            "stated_preference": "CS in USA",
            "underlying_objective": "an international tech career",
            "drivers": ["family", "career"], "constraints": []}
        assert rows[0].verification_status == "self_reported"

        service = JourneyService(db)
        journey = service.ensure_counselor(student.workspace_id)
        snapshot = StudentSnapshotService(db).build(student.workspace_id)
        requirement = ProfileRequirement(
            key="goal.constraints", tier="important", source_type="record_field",
            source_key="goal", source_path="details.constraints",
            selector="any_present", question="What limits matter?", priority=85,
            version=1, enabled=True)
        assert ProfileRequirementRegistry(db).evaluate(
            requirement, snapshot, {}) == (True, True)
        moved = advance_discovery_stage(
            service, student.workspace_id, journey, identity_ready=True,
            foundation_ready=True, goal_records=snapshot.records["goal"])
        assert moved.current_stage == DIRECTION
