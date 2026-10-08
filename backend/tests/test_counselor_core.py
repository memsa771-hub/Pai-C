"""Bounded student context projection retained after Core removal."""

from datetime import datetime, timezone


from app.counseling.context_projection import compact_student_context
from app.counseling.understanding import StudentUnderstandingBuilder
from app.memory.student_snapshot import StudentSnapshot


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
