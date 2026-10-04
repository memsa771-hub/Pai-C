"""Deterministic Hub behavior over a changing student understanding."""

from datetime import datetime, timezone
from types import SimpleNamespace

from app.counseling.baseline import changed_domains, metadata, save
from app.counseling.continuous_discovery import evaluate_continuous_discovery
from app.counseling.evaluator import CounselingEvaluator
from app.counseling.policy import CounselingPolicy
from app.counseling.turn_semantics import validated_journey_intent
from app.counseling.understanding import StudentUnderstandingBuilder, student_mirror
from app.memory.student_snapshot import StudentSnapshot


def _view(records, status="confirmed"):
    snapshot = StudentSnapshot("student", {}, records, (), datetime.now(timezone.utc))
    return StudentUnderstandingBuilder().build(
        "student", snapshot=snapshot, baseline={"status": status, "version": 1})


def _policy(view, semantics=None, *, changes=(), conflict=None, journey=None):
    state = CounselingEvaluator().derive(
        message="", vault_context=view, journey=journey,
        completion={"personalizedCounselingEligible": True},
        turn_semantics=semantics or {}, changed_domains=changes,
        active_conflict=conflict)
    return CounselingPolicy().decide(state)


def test_discovery_uses_relevance_and_allows_zero_questions():
    records = {
        "education": [{"id": "school", "qualification_name": "A Levels",
                       "canonical_level": "upper_secondary", "result": {"grade": "B"}}],
        "goal": [{"id": "goal", "title": "Explore fields",
                  "details": {"motivation": "find a good direction"}}],
    }
    view = _view(records)
    idle = _policy(view)
    assert idle.move == "COUNSEL" and idle.max_questions == 0
    assert idle.continuous_discovery["next_discovery_move"] == "NONE"
    asked = _policy(view, {"topic_focus": "strengths"})
    assert asked.move == "ASK" and asked.focus == "strengths"
    assert asked.max_questions == 1
    changed = _policy(view, changes=("activities", "exposure"))
    assert changed.move == "REFLECT" and changed.max_questions == 0
    assert changed.continuous_discovery["affected_domains"] == ("activities", "exposure")
    conflict = _policy(view, conflict={"summary": "education differs"})
    assert conflict.move == "CLARIFY" and conflict.max_questions == 1


def test_decision_gap_prefers_exploration_over_repeated_questions():
    view = _view({
        "education": [{"id": "school", "qualification_name": "A Levels",
                       "canonical_level": "upper_secondary", "result": {"grade": "A"}}],
        "goal": [{"id": "goal", "title": "Compare fields",
                  "details": {"motivation": "choose carefully"}}],
        "student_voice_statement": [{"id": "voice", "voice_type": "interest",
                                     "direction": "Computer Science", "statement": "I like CS"}],
    })
    decision = {"type": "compare_fields", "candidates": ["Computer Science", "Economics"]}
    policy = _policy(view, {"decision_intent": decision})
    assert policy.move == "EXPLORE" and policy.max_questions == 0
    assert not policy.decision_sufficiency["recommendation_ready"]
    assert policy.continuous_discovery["next_discovery_move"] == "EXPLORE"


def test_existing_transcript_is_used_for_relevant_academic_gap():
    view = _view({
        "education": [{"id": "school", "qualification_name": "A Levels",
                       "canonical_level": "upper_secondary"}],
        "document": [{"id": "transcript", "name": "Transcript", "document_type": "transcript"}],
    })
    signal = evaluate_continuous_discovery(view, {"topic_focus": "academic_performance"})
    assert signal.next_discovery_move == "REFLECT"
    assert signal.focus == "use uploaded evidence"
    assert _policy(view, {"topic_focus": "academic_performance"}).max_questions == 0


def test_journey_intent_requires_supported_type_and_exact_evidence():
    message = "I want to properly explore psychology and economics."
    proposal = {"action": "upsert", "journey_type": "direction_discovery",
                "goal_title": "Explore psychology and economics",
                "relationship": "same_or_new", "quote": message}
    assert validated_journey_intent(proposal, message)["journey_type"] == "direction_discovery"
    assert validated_journey_intent(proposal, "Maybe psychology sounds interesting.") is None
    assert validated_journey_intent({**proposal, "journey_type": "invented"}, message) is None
    assert validated_journey_intent({**proposal, "quote": "unspoken intent"}, message) is None
    assert validated_journey_intent({"action": "complete", "quote": "complete this"},
                                    "Please complete this") == {"action": "complete"}


def test_multilingual_journey_proposals_share_one_structural_contract():
    messages = (
        "I want to explore psychology and economics seriously.",
        "Quiero explorar psicología y economía en serio.",
        "أريد أن أستكشف علم النفس والاقتصاد بجدية.",
    )
    for message in messages:
        proposal = {"action": "upsert", "journey_type": "direction_discovery",
                    "goal_title": "Explore study directions", "relationship": "same_or_new",
                    "quote": message}
        assert validated_journey_intent(proposal, message) == {
            "action": "upsert", "journey_type": "direction_discovery",
            "goal_title": "Explore study directions", "relationship": "same_or_new"}


def test_longitudinal_counseling_adapts_across_22_structured_turns():
    records = {}
    workspace = SimpleNamespace(settings={})
    turns = [
        ("confused", None, None),
        ("education", "education", None),
        ("grades", "education", None),
        ("parent", "external_influence", None),
        ("peer", "external_influence", None),
        ("activity", "activity", None),
        ("goal", "goal", None),
        ("mirror", None, None),
        ("confirm", None, None),
        ("interest", "student_voice_statement", "interests"),
        ("coding", "exploration_experience", None),
        ("debugging", "exploration_experience", None),
        ("dislike", "student_voice_statement", None),
        ("comparison", None, "decision"),
        ("evidence_gap", None, "decision"),
        ("economics_exposure", "exploration_experience", None),
        ("reflection", "exploration_experience", None),
        ("project", "project", None),
        ("narrow", "student_voice_statement", None),
        ("recompare", None, "decision"),
        ("correction", "education", None),
        ("review", None, None),
    ]
    additions = {
        "education": {"id": "school", "qualification_name": "A Levels",
                      "canonical_level": "upper_secondary"},
        "grades": {"id": "school", "qualification_name": "A Levels",
                   "canonical_level": "upper_secondary", "result": {"grade": "Math A, Economics A"}},
        "parent": {"id": "father", "influencer_type": "parent", "source_label": "father",
                   "suggested_direction": "Medicine"},
        "peer": {"id": "friend", "influencer_type": "peer", "source_label": "friend",
                 "suggested_direction": "Computer Science"},
        "activity": {"id": "club", "title": "Economics club", "activity_type": "club"},
        "goal": {"id": "goal", "title": "Explore bachelor directions",
                 "details": {"motivation": "make an informed choice"}},
        "interest": {"id": "interest", "voice_type": "interest", "direction": "Computer Science",
                     "statement": "I am curious about Computer Science"},
        "coding": {"id": "coding", "domain": "Computer Science", "title": "Coding trial",
                   "activity_status": "planned", "exposure_level": "none"},
        "debugging": {"id": "debugging", "domain": "Computer Science", "title": "Debugging",
                      "activity_status": "completed", "student_reflection": {"enjoyed": True}},
        "dislike": {"id": "dislike", "voice_type": "preference", "direction": "Computer Science",
                   "statement": "I dislike working alone for hours"},
        "economics_exposure": {"id": "economics", "domain": "Economics", "title": "Economics shadowing",
                               "activity_status": "completed", "student_reflection": {"enjoyed": True}},
        "reflection": {"id": "economics2", "domain": "Economics", "title": "Policy project",
                       "activity_status": "completed", "student_reflection": {"enjoyed": True}},
        "project": {"id": "project", "name": "Data project"},
        "narrow": {"id": "narrow", "voice_type": "direction", "direction": "Economics",
                   "statement": "Economics is my own leading choice"},
        "correction": {"id": "school", "qualification_name": "A Levels",
                       "canonical_level": "upper_secondary", "result": {"grade": "Math A, Economics B"}},
    }
    sizes, moves = [], []
    for index, (label, family, focus) in enumerate(turns):
        if label in additions:
            item = additions[label]
            bucket = records.setdefault(family, [])
            bucket[:] = [old for old in bucket if old.get("id") != item["id"]]
            bucket.append(item)
        status = "confirmed" if index >= 8 else "discovering"
        view = _view(records, status)
        if label == "mirror":
            assert "A Levels" in student_mirror(view)
            save(workspace, status="mirror_review", view=view)
        if label == "confirm":
            save(workspace, status="confirmed", view=view)
        changes = changed_domains(view, metadata(workspace)) if index > 8 else []
        semantics = ({"decision_intent": {"type": "compare_fields",
                     "candidates": ["Computer Science", "Economics"]}}
                     if focus == "decision" else {"topic_focus": focus} if focus else {})
        if index >= 8:
            policy = _policy(view, semantics, changes=changes)
            moves.append(policy.move)
            assert policy.max_questions <= 1
            if policy.move == "ASK":
                assert policy.focus in ({gap["focus"] for gap in view["open_gaps"]}
                                        | {"current_qualification", "current_year", "current_subjects"})
            if focus == "decision" and not policy.decision_sufficiency["recommendation_ready"]:
                assert policy.move in {"ASK", "EXPLORE", "CLARIFY"}
            if changes:
                save(workspace, status="confirmed", view=view)
        sizes.append(sum(len(value) for value in records.values()))
    assert len(turns) >= 20 and sizes[-1] > sizes[0]
    assert "EXPLORE" in moves and "REFLECT" in moves and "COUNSEL" in moves
    assert all(item.get("suggested_direction") != "Economics" for item in records["external_influence"])
    assert any(item.get("direction") == "Economics" for item in records["student_voice_statement"])
