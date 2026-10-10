"""Read-only, redacted session export. Run with python -m scripts.export_counselor_session.

Usage is emitted to application logs, not persisted in the database. Supply
--usage-log (repeatable) with saved backend/worker logs to include those calls.
Costs are estimates using scripts/eval/model_prices.json; absent logs/prices
are reported as unavailable, never as zero. Numeric token counts are usage
metrics; credential tokens are never exported.
"""
import argparse
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

from sqlalchemy import select, text

from app.database import new_session
from app.pai_c.memory import MemoryService
from app.models import (CounselorNotedQuestion, CounselorTurnDecision,
                        EventRecord, Roadmap, StudentJourney, Workspace)
from scripts.eval.cost import load_prices, token_record

ROOT = Path(__file__).resolve().parents[2]
_PRIVATE_KEY = re.compile(r"email|password|secret|token|credential|authorization|api[_-]?key", re.I)
_ENV_SECRET = re.compile(r"(?:^|_)(?:KEY|TOKEN|PASSWORD|SECRET|EMAIL)$", re.I)
_EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[a-zA-Z]{2,}")
_CREDENTIAL = re.compile(
    r"(?i)\b(?:password|secret|(?:access[_ -]?|refresh[_ -]?)?token|api[_ -]?key|authorization)"
    r"\s*(?:[:=]|\bis\b)\s*(?:\"[^\"]*\"|'[^']*'|\S+)|\bBearer\s+\S+|"
    r"\bsk-[\w-]+|\beyJ[\w-]+\.[\w-]+\.[\w-]+|"
    r"[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@|"
    r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----")
_USAGE = re.compile(
    r"counselor_token_usage phase=(\S+) turn_id=(\S+) model=(\S+) "
    r"input=(\d+) cached_input=(\d+) output=(\d+) reasoning=(\d+)")


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {str(k): redact(v, secrets) for k, v in value.items()
                if not _PRIVATE_KEY.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return _EMAIL.sub("[REDACTED]", _CREDENTIAL.sub("[REDACTED]", value))
    return value


def row_data(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


def logged_usage(paths, event_ids):
    prices = load_prices(Path(__file__).parent / "eval/model_prices.json")
    calls = []
    for path in paths:
        with Path(path).open(encoding="utf-8", errors="replace") as stream:
            for line_number, line in enumerate(stream, 1):
                match = _USAGE.search(line)
                if not match or match[2] not in event_ids:
                    continue
                phase, event_id, model = match.group(1, 2, 3)
                incoming, cached, outgoing, reasoning = map(int, match.group(4, 5, 6, 7))
                usage = SimpleNamespace(prompt_tokens=incoming, completion_tokens=outgoing,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning))
                try:
                    record = token_record(usage, model, phase, prices)
                except ValueError:
                    record = dict(phase=phase, model=model, input=incoming,
                                  cached_input=cached, output=outgoing,
                                  reasoning=reasoning, cost_usd=None)
                calls.append({**record, "source_event_id": event_id,
                              "log_line": line_number})
    return {"status": "available" if calls else "unavailable",
            "cost_basis": "estimated from model_prices.json; not provider billing",
            "coverage": "Only supplied logs with workspace event IDs; untagged calls cannot be attributed safely",
            "calls": calls}


def export_session(db, workspace_id, usage_logs=()):
    """SELECT only. Caller owns the transaction; never commits or writes rows."""
    with db.no_autoflush:
        if db.get(Workspace, workspace_id) is None:
            raise ValueError("Workspace not found")
        def rows(model, workspace_column="workspace_id", *order):
            return db.scalars(select(model).where(
                getattr(model, workspace_column) == workspace_id).order_by(*order)).all()

        events = rows(EventRecord, "network_id", EventRecord.timestamp, EventRecord.id)
        actions = [dict(id=e.id, timestamp=e.timestamp, type=e.type,
                        source_event_id=(e.metadata_ or {}).get("trigger_event_id"),
                        payload=e.payload) for e in events if e.type.startswith("counselor.action.")]
        decisions = rows(CounselorTurnDecision)
        conversation = []
        for event in events:
            if event.type != "workspace.message.posted":
                continue
            source = event.source or ""
            if not (source.startswith("human:") or source == "openagents:pai"):
                continue
            payload = event.payload or {}
            if payload.get("message_type", "chat") not in {"chat", "counselor_mirror", "operator_result"}:
                continue
            conversation.append(dict(id=event.id, timestamp=event.timestamp,
                role="student" if source.startswith("human:") else "pai",
                channel=event.target, content=payload.get("content", ""),
                message_type=payload.get("message_type", "chat"),
                actions=[a for a in actions if a["source_event_id"] == event.id],
                decisions=[row_data(d) for d in decisions if d.source_event_id == event.id]))
        notebook_export = MemoryService(db).export_truth_map(workspace_id)
        journeys = rows(StudentJourney, "workspace_id", StudentJourney.created_at, StudentJourney.id)
        roadmaps = rows(Roadmap, "workspace_id", Roadmap.created_at, Roadmap.id)
        mirrors = [dict(journey_id=j.id, draft=j.counselor_summary_draft)
                   for j in journeys if j.counselor_summary_draft]
        mirror_events = [dict(event_id=e.id, timestamp=e.timestamp, payload=e.payload)
                         for e in events if (e.payload or {}).get("message_type") == "counselor_mirror"]
        facts = []
        for roadmap in roadmaps:
            for fact in (roadmap.fit_dimensions or {}).get("facts", []):
                facts.append(dict(roadmap_id=roadmap.id, fact=fact))
        result = dict(workspace_id=workspace_id, exported_at=datetime.now(timezone.utc),
            conversation=conversation, actions=actions,
            notebook=notebook_export,
            noted_questions=[row_data(q) for q in rows(CounselorNotedQuestion,
                "workspace_id", CounselorNotedQuestion.created_at, CounselorNotedQuestion.id)],
            mirror_drafts=mirrors, mirror_history=mirror_events,
            mirror_history_coverage="Posted payloads plus current draft; historical confirmation/edit statuses are not stored",
            research_facts_used=facts,
            roadmaps=[{**row_data(r), "status": r.generation_status,
                       "missing_facts": (r.fit_dimensions or {}).get("missing_facts", []),
                       "research_sources": r.sources} for r in roadmaps],
            usage=logged_usage(usage_logs, {e.id for e in events}))
        secrets = [v for k, v in os.environ.items() if _ENV_SECRET.search(k) and v]
        return redact(result, secrets)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=UUID)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--usage-log", type=Path, action="append", default=[],
                        help="Saved backend/worker log; repeat for multiple files")
    args = parser.parse_args()
    workspace_id = str(args.workspace)
    with new_session() as db:
        if db.bind.dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        elif db.bind.dialect.name == "sqlite":
            db.execute(text("PRAGMA query_only=ON"))
        result = export_session(db, workspace_id, args.usage_log)
        db.rollback()
    output = args.out or ROOT / "eval_reports/sessions" / (
        workspace_id + "-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print("Session exported")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Database/log exceptions can contain credentials or private paths.
        raise SystemExit("Export failed; check workspace, database access, log files and output path") from None
