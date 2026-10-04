"""The active Counselor answers in prose from bounded student context."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, patch

from app.counseling.core import CounselorCore, compact_student_context
from app.counseling.runtime import _run_turn
from app.counseling.understanding import StudentUnderstandingBuilder
from app.memory.student_snapshot import StudentSnapshot


class Provider:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    async def respond(self, messages, system_prompt):
        self.calls.append((messages, system_prompt))
        return self.reply


def _understanding():
    return {
        "education": {
            "nodes": [{"id": "private", "qualification_name": "A Levels",
                       "academic_status": "current",
                       "provenance": {"source": "conversation"}}],
            "courses": [{"id": "course-private", "name": "Math"}],
        },
        "influences": {"nodes": [{"id": "private", "source_type": "parent",
                                 "direction": "Computer Science",
                                 "student_quote": "My father suggests CS"}]},
        "student_voice": {"current_direction": {"status": "uncertain"}},
        "baseline": {"status": "unconfirmed"},
        "open_gaps": [{"focus": "current_subjects"}],
    }


def test_compact_context_keeps_known_education_without_internal_state():
    context = compact_student_context(_understanding())
    assert context["education"] == [{
        "qualification_name": "A Levels", "academic_status": "current"}]
    assert context["courses"] == [{"name": "Math"}]
    assert context["influences"][0]["direction"] == "Computer Science"
    assert "baseline" not in context
    assert "open_gaps" not in context
    assert "private" not in str(context)


def test_context_selects_relevant_education_and_supported_connections():
    view = {
        "identity": {"preferred_name": {"value": "Amina"},
                     "date_of_birth": {"value": "2004-01-01"}},
        "education": {
            "nodes": [
                {"id": "old", "qualification_name": "A Levels", "academic_status": "completed"},
                {"id": "current", "qualification_name": "BS Computer Science",
                 "academic_status": "current", "field_of_study": "Computer Science"},
            ],
            "courses": [{"id": "course", "education_id": "current", "name": "Machine Learning"}],
            "edges": [{"from": "old", "to": "current", "relation": "precedes"}],
        },
        "projects": {"nodes": [{"id": "p1", "name": "Research assistant"},
                               {"id": "p2", "name": "Vision model"}]},
        "skills": {"nodes": [{"id": "s1", "name": "Python"}]},
        "goals": {"nodes": [{"id": "g1", "title": "AI master's",
                              "details": {"field_of_study": "Computer Science"}}]},
        "relationships": [
            {"from": {"type": "project", "id": "p2"},
             "to": {"type": "skill", "id": "s1"}, "relation": "supports"},
            {"from": {"type": "education", "id": "current"},
             "to": {"type": "goal", "id": "g1"}, "relation": "relevant_to"},
        ],
    }
    context = compact_student_context(view, "Tell me about my Vision model and Python")
    assert context["identity"] == {"preferred_name": "Amina"}
    assert context["education"][0]["qualification_name"] == "BS Computer Science"
    assert context["projects"][0]["name"] == "Vision model"
    assert "Machine Learning belongs to BS Computer Science" in context["connections"]
    assert "Vision model supports Python" in context["connections"]
    assert "BS Computer Science has matching stated field to AI master's" in context["connections"]
    assert "date_of_birth" not in str(context)
    assert "p2" not in str(context)


def test_context_does_not_invent_or_leak_unselected_links():
    view = {
        "education": {"nodes": [{"id": "e", "qualification_name": "BS CS"}],
                      "courses": [{"id": "c", "education_id": "other", "name": "Physics"}]},
        "skills": {"nodes": [{"id": "s", "name": "Python"}]},
        "relationships": [{"from": {"type": "project", "id": "missing"},
                           "to": {"type": "skill", "id": "s"}, "relation": "supports"}],
    }
    context = compact_student_context(view, "Physics")
    assert "connections" not in context


def test_short_follow_up_uses_previous_student_topic_for_record_selection():
    provider = Provider("The robotics project used Python.")
    view = {"projects": {"nodes": [
        {"id": "first", "name": "Debate club"},
        {"id": "second", "name": "Robotics project"},
    ]}}
    asyncio.run(CounselorCore(provider).respond(
        student_message="And that?",
        recent_conversation=[{"role": "user", "content": "Tell me about my robotics project"},
                             {"role": "assistant", "content": "Let's look at it."}],
        understanding=view,
    ))
    assert "Robotics project" in provider.calls[0][1]


def test_projection_consumes_real_understanding_education_links():
    snapshot = StudentSnapshot(
        "student", {}, {
            "education": [{"id": "degree", "qualification_name": "BS CS",
                           "canonical_level": "bachelor", "academic_status": "current"}],
            "course": [{"id": "course", "education_id": "degree", "name": "Algorithms"}],
            "project": [{"id": "project", "name": "Compiler", "details": {"skills": ["Python"]}}],
            "skill": [{"id": "skill", "name": "Python"}],
        }, (), datetime.now(timezone.utc),
    )
    view = StudentUnderstandingBuilder().build("student", snapshot=snapshot)
    context = compact_student_context(view, "Compiler Python Algorithms")
    assert "Algorithms belongs to BS CS" in context["connections"]
    assert "Compiler supports Python" in context["connections"]


def test_core_uses_one_natural_text_model_call_with_recent_context():
    provider = Provider("Your father's suggestion is one input. What school work do you enjoy?")
    reply = asyncio.run(CounselorCore(provider).respond(
        student_message="My father wants CS but I am unsure.",
        recent_conversation=[{"role": "user", "content": "I study A Levels."}],
        understanding=_understanding(),
    ))
    assert reply == provider.reply
    messages, prompt = provider.calls[0]
    assert len(provider.calls) == 1
    assert messages[-1]["content"] == "My father wants CS but I am unsure."
    assert "A Levels" in prompt and "Math" in prompt
    assert "counselor_state" not in prompt
    assert "Return a JSON object" not in prompt


def test_legacy_json_is_only_a_visibility_guard():
    provider = Provider('{"response":"What are you studying now?",'
                        '"counselor_state":{"next_move":{"type":"ASK"}}}')
    reply = asyncio.run(CounselorCore(provider).respond(
        student_message="hi", recent_conversation=[], understanding={}))
    assert reply == "What are you studying now?"


def test_text_and_voice_turns_use_the_same_core_and_background_learning():
    async def run():
        db = Mock()
        snapshot = Mock()
        core_reply = AsyncMock(return_value="What subjects are you studying?")
        post = AsyncMock(return_value="assistant-event")
        with patch("app.counseling.runtime.config.PAI_API_KEY", "server-key"), \
             patch("app.counseling.runtime.config.PAI_MEMORY_CONTEXT_ENABLED", False), \
             patch("app.counseling.runtime._build_conversation_context",
                   return_value=[]), \
             patch("app.memory.student_snapshot.StudentSnapshotService") as snapshots, \
             patch("app.counseling.understanding.StudentUnderstandingBuilder") as builders, \
             patch("app.counseling.core.CounselorCore") as core, \
             patch("app.counseling.runtime._post_response", post), \
             patch("app.memory.turn_hook.enqueue_turn_extraction") as extract:
            snapshots.return_value.build.return_value = snapshot
            builders.return_value.build.return_value = _understanding()
            core.return_value.respond = core_reply
            for marker in ({}, {"voice_delegation_id": "live-turn"}):
                await _run_turn(db, "student", {
                    "id": "student-event", "target": "channel/pai-counselor",
                    "payload": {"content": "high school"},
                    "metadata": marker,
                }, 0)
            assert core_reply.await_count == 2
            assert all(call.kwargs["student_message"] == "high school"
                       for call in core_reply.await_args_list)
            assert post.await_args_list[0].kwargs["metadata"] is None
            assert post.await_args_list[1].kwargs["metadata"] == {
                "voice_delegation_id": "live-turn"}
            assert extract.call_count == 2
            assert all(call.kwargs["user_event_id"] == "student-event"
                       for call in extract.call_args_list)
    asyncio.run(run())
