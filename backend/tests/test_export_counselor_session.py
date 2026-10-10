"""Session exports use offline data, SELECTs only, and redact credentials."""
import json
from unittest.mock import patch

from app.models import (CounselorNotebook, CounselorNotebookHistory, CounselorNotedQuestion,
                        CounselorTurnDecision, EventRecord, Workspace, StudentJourney, Roadmap)
from scripts.counselor_eval_support import StudentSession
from scripts.export_counselor_session import export_session


def test_export_order_redaction_isolation_and_no_writes(tmp_path):
    with StudentSession() as student, student.factory() as db:
        workspace = student.workspace_id
        db.add(Workspace(id="00000000-0000-0000-0000-000000000002", name="Other"))
        for event_id, stamp, source, payload in [
            ("later", 20, "openagents:pai", {"content": "What did you finish?"}),
            ("earlier", 10, "human:student@example.test", {"content":
                "Contact student@example.test password=hunter2 token=private-value sk-example-secret",
                "email": "student@example.test", "api_key": "never-export"}),
            ("foreign", 1, "human:other", {"content": "Foreign workspace"}),
        ]:
            db.add(EventRecord(id=event_id, network_id=workspace if event_id != "foreign" else
                "00000000-0000-0000-0000-000000000002", type="workspace.message.posted",
                source=source, target="channel/pai", timestamp=stamp, payload=payload))
        db.add(EventRecord(id="action", network_id=workspace, type="counselor.action.note_question",
            source="openagents:pai", target="channel/pai", timestamp=11,
            metadata_={"trigger_event_id": "earlier"}, payload={"status": "recorded"}))
        db.add(CounselorTurnDecision(workspace_id=workspace, source_event_id="earlier",
            source_timestamp=10, move="note_question"))
        db.add(CounselorNotebook(workspace_id=workspace, notebook={"schema_version": 2, "private_notes": "deployment-secret", "legacy_v1": {"note": "private archival payload"}},
            version=2, last_event_id="earlier"))
        db.add(CounselorNotebookHistory(workspace_id=workspace, notebook={"schema_version": 2, "private_notes": "older", "legacy_v1": {"note": "private archival payload"}},
            version=1, source_event_id="earlier"))
        journey = StudentJourney(id="journey-export", workspace_id=workspace,
            journey_type="counselor_decision", title="Study", current_stage="MIRROR",
            counselor_summary_draft={"type": "mirror", "version": 2,
                "notebook_version": 2, "status": "awaiting_confirmation", "mirror": {"intro": "You"}})
        db.add(journey)
        db.flush()
        db.add(Roadmap(id="roadmap-export", workspace_id=workspace, journey_id=journey.id,
            origin="stated_goal", title="Explore", generation_status="needs_info",
            fit_dimensions={"missing_facts": ["entry"], "facts": [{"fact_id": "f1",
                "source_url": "https://example.test/entry", "label": "unconfirmed"}]}))
        db.add(CounselorNotedQuestion(workspace_id=workspace, source_event_id="earlier",
                                    question_to_research="What are the entry requirements?"))
        db.commit()
        log = tmp_path / "worker.log"
        log.write_text("counselor_token_usage phase=counselor turn_id=earlier model=gpt-6-sol "
            "input=100 cached_input=20 output=30 reasoning=5\n"
            "counselor_token_usage phase=counselor turn_id=foreign model=gpt-6-sol "
            "input=50 cached_input=0 output=10 reasoning=0\n")
        with patch.dict("os.environ", {"TEST_API_KEY": "deployment-secret"}), \
                patch.object(db, "commit", side_effect=AssertionError("export wrote")):
            result = export_session(db, workspace, [log])
        assert [m["id"] for m in result["conversation"]] == ["earlier", "later"]
        assert result["conversation"][0]["actions"][0]["type"] == "counselor.action.note_question"
        assert result["conversation"][0]["decisions"][0]["move"] == "note_question"
        assert result["notebook"]["latest"]["version"] == 2
        assert result["notebook"]["history"][0]["version"] == 1
        for version in [result["notebook"]["latest"], *result["notebook"]["history"]]:
            assert version["notebook"]["schema_version"] == 2
            assert version["notebook"]["has_legacy_v1"] is True
            assert "legacy_v1" not in version["notebook"]
        assert "private archival payload" not in json.dumps(result)
        assert result["noted_questions"][0]["status"] == "open"
        assert result["mirror_drafts"][0]["draft"]["version"] == 2
        assert result["roadmaps"][0]["missing_facts"] == ["entry"]
        assert result["research_facts_used"][0]["fact"]["label"] == "unconfirmed"
        assert len(result["usage"]["calls"]) == 1
        assert result["usage"]["calls"][0]["cost_usd"] > 0
        serialized = json.dumps(result)
        for forbidden in ["student@example.test", "hunter2", "private-value", "sk-example-secret",
                          "never-export", "deployment-secret", "Foreign workspace"]:
            assert forbidden not in serialized
        assert not db.new and not db.dirty and not db.deleted


def test_export_missing_usage_not_reported_as_zero():
    with StudentSession() as student, student.factory() as db:
        result = export_session(db, student.workspace_id)
        assert result["usage"]["status"] == "unavailable"
        assert result["usage"]["calls"] == []
