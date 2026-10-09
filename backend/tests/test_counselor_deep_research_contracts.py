"""Research assertions retained from retired evaluators; no provider calls."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from app.pai_c.deep.polish import polish_reply, question_count
from app.pai_c.stages import require_counselor_transition
from app.plugins._shared.verification import SourceVerifier, official_url
from app.plugins.gap_assessment import assess, assess_rule
from app.plugins.roadmap_builder import build


def test_deep_research_keeps_reported_evidence_and_requires_cited_rules():
    rule = {"field": "test.score", "source_url": "https://example.edu/entry",
            "checked_at": "2026-10-06", "comparator": "gte", "threshold": 7}
    fact = {"value": 7.5, "evidence_level": "student_reported"}
    assert assess_rule(rule, {"test.score": fact})["student_evidence"] == "student_reported"
    assert assess_rule({**rule, "source_url": ""}, {"test.score": fact})["status"] == "unknown"
    assert assess_rule(rule, {})["status"] == "unknown"
    remedial = {**rule, "remediation": {"action": "Complete a preparatory route",
                                         "source_url": "https://example.edu/preparation"}}
    assert assess_rule(remedial, {"test.score": 6})["status"] == "fixable"
    assert assess_rule({**rule, "field": "education.transcript"}, {})["status"] == "unknown"


def test_deep_research_rethink_and_single_question_contracts():
    assert require_counselor_transition("PROPOSED", "DIRECTION") == "DIRECTION"
    assert question_count(polish_reply("One? Two?")) == 1


def test_official_source_rejects_lookalike_domain():
    assert not official_url("https://example.edu.evil.test/entry", {"example.edu"})
