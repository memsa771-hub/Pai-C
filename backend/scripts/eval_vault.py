"""Measure what the Vault keeps from synthetic student conversations.

Each golden case runs through the real pipeline on an isolated SQLite student:
student message → memory.extract → memory.reconcile → Vault. The result is
mapped to facets (scripts/eval/vault_golden.py) and scored against what the
case says is true.

Modes:
  default   replay recorded extractor outputs (no model calls, no cost)
  --live    call the configured extractor model under --max-cost-usd and save
            the raw outputs as recordings for later offline replays

Usage:
  python -m scripts.eval_vault
  python -m scripts.eval_vault --live --max-cost-usd 1
  python -m scripts.eval_vault --case ru-fsc-cricket --language ur
"""
import argparse
import asyncio
import contextlib
import hashlib
import importlib.util
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.counselor_eval_support import StudentSession
from scripts.eval import vault_golden

ROOT = Path(__file__).resolve().parent
RECORDINGS = vault_golden.CASES / "recordings"
RESULTS = ROOT / "results" / "vault_eval"
PRICES = ROOT / "eval" / "model_prices.json"
VERSIONS = ROOT.parent / "alembic" / "versions"


def _migration(name: str):
    spec = importlib.util.spec_from_file_location(f"migration_{name}", VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def production_field_definitions() -> list[dict]:
    """The Vault fields production has after every migration, as upsert specs.

    074 seeds the base fields; 078 gives preferences, career, mobility and
    location a source policy; 085 adds two preference fields without one.
    The eval must see the same fields the real extractor is shown.
    """
    specs = []
    for field in _migration("074_pai_os_baseline")._VAULT_FIELDS:
        spec = {k: v for k, v in field.items() if k != "id"}
        if spec["category"] == "location":
            spec["source_policy"] = {"temporal_change": "student_transition"}
        elif spec["category"] in ("preferences", "career", "mobility"):
            spec["source_policy"] = {"allowed_sources": ["user_explicit", "conversation"],
                                     "authority_rank": {"user_explicit": 100, "conversation": 80}}
        specs.append(spec)
    # Mirrors the two INSERTs in alembic/versions/085_counselor_discovery_slots.py.
    specs.append({"key": "preferences.location_limits", "category": "preferences", "data_type": "array",
                  "validation_schema": {"type": "array", "maxItems": 30,
                                        "items": {"type": "string", "minLength": 1, "maxLength": 200}},
                  "cardinality": "single", "conflict_policy": "latest_wins", "sensitivity": "normal",
                  "searchable": True, "description": "Places the student can or cannot study or work",
                  "context_tags": ["counseling", "matching"], "required_for": ["counseling"],
                  "profile_priority": 65})
    specs.append({"key": "preferences.study_load", "category": "preferences", "data_type": "string",
                  "validation_schema": {"type": "string", "enum": ["full_time", "part_time", "flexible"]},
                  "cardinality": "single", "conflict_policy": "latest_wins", "sensitivity": "normal",
                  "searchable": False, "description": "Full-time or part-time study availability",
                  "context_tags": ["counseling"], "required_for": ["counseling"], "profile_priority": 55})
    return specs


def prompt_fingerprint() -> str:
    """Changes whenever the extractor's instructions or field list change,
    which is when a recording stops being a faithful replay."""
    from app.memory.extractor import SYSTEM_PROMPT
    keys = sorted(spec["key"] for spec in production_field_definitions())
    return hashlib.sha256((SYSTEM_PROMPT + "\n" + ",".join(keys)).encode()).hexdigest()[:16]


class VaultSession(StudentSession):
    """A StudentSession whose Vault has production's field definitions."""

    def __enter__(self):
        super().__enter__()
        from app.memory.field_definitions import VaultFieldDefinitionService
        with self.factory() as db:
            fields = VaultFieldDefinitionService(db)
            for spec in production_field_definitions():
                fields.upsert_definition(spec)
            db.commit()
        return self

    def student_message(self, text: str) -> str:
        """Persist one student message and queue its extraction, as a turn does."""
        from app.memory.turn_hook import enqueue_turn_extraction
        from app.models import EventRecord
        event_id = str(uuid.uuid4())
        with self.factory() as db:
            db.add(EventRecord(id=event_id, network_id=self.workspace_id, type="workspace.message.posted",
                               source=f"human:{self.user_id}", target="channel/pai-counselor",
                               payload={"content": text}, timestamp=self.next_timestamp()))
            db.commit()
            enqueue_turn_extraction(db, workspace_id=self.workspace_id, channel_target="channel/pai-counselor",
                                    user_event_id=event_id, assistant_event_id=None, agent_name="pai")
        return event_id

    def open_issues(self) -> int:
        from sqlalchemy import func, select
        from app.models import ProfileIssue
        with self.factory() as db:
            return db.scalar(select(func.count()).select_from(ProfileIssue).where(
                ProfileIssue.workspace_id == self.workspace_id, ProfileIssue.status == "open")) or 0


class _DropLog(logging.Handler):
    """Collects the extractor's 'dropped candidate' reasons for the report."""

    def __init__(self):
        super().__init__(logging.INFO)
        self.reasons: list[str] = []

    def emit(self, record):
        message = record.getMessage()
        if "dropped candidate" in message:
            self.reasons.append(message.split("—", 1)[-1].strip())


async def run_case(case: dict, model) -> dict:
    """Run one case through extraction and reconciliation; return its score.

    `model(case_id, turn_index, kwargs)` returns the extractor's raw output.
    """
    from app.memory import extractor
    drops = _DropLog()
    logger = logging.getLogger("app.memory.extractor")
    logger.addHandler(drops)
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    turn_index = {"value": 0}

    async def extractor_call(**kwargs):
        return await model(case["id"], turn_index["value"], kwargs)

    try:
        with VaultSession() as student, patch.object(extractor, "chat_completion", extractor_call):
            for index, text in enumerate(case["turns"]):
                turn_index["value"] = index
                student.student_message(text)
                await student.extract_and_reconcile()
            profile = student.profile()
            issues = student.open_issues()
    finally:
        logger.removeHandler(drops)
        logger.setLevel(previous_level)
    result = vault_golden.score_case(case, vault_golden.facets_from_profile(profile))
    rejected = [c for c in profile["candidates"] if c["status"] in ("rejected", "needs_review")]
    result.update({
        "extractor_drops": drops.reasons,
        "reconciler_rejected": [f"{c['key']}: {c['status']} ({c['reason']})" for c in rejected],
        "open_issues": issues,
        "accepted_without_quote": sum(1 for c in profile["candidates"] if c["status"] == "accepted"
                                      and not (c.get("evidence") or {}).get("quote")),
    })
    return result


def recorded_model(fingerprint: str):
    """Replays saved extractor outputs; a missing or stale recording is reported, not faked."""
    async def call(case_id, turn_index, kwargs):
        path = RECORDINGS / f"{case_id}.json"
        if not path.exists():
            raise LookupError("not_recorded")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("prompt_fingerprint") != fingerprint:
            raise LookupError("stale_recording")
        return data["outputs"][turn_index]
    return call


@contextlib.contextmanager
def live_model(max_cost_usd: float, fingerprint: str):
    """Real extractor calls under a cost cap; each case's outputs are saved."""
    from app.config import config
    from app.inference.gateway import complete
    from scripts.eval.cost import BudgetReached, UsageLedger, load_prices
    from scripts.eval_counselor_deep import live_tracking
    if not (getattr(config, "MEMORY_EXTRACTOR_API_KEY", "") or config.PAI_API_KEY):
        raise SystemExit("--live needs the extractor model key in the environment")
    ledger = UsageLedger(load_prices(PRICES), max_cost_usd)
    outputs: dict[str, list[str]] = {}

    async def call(case_id, turn_index, kwargs):
        try:
            raw = await complete(**kwargs)
        except BudgetReached:
            # Keep what was measured so far; the remaining cases are skipped.
            raise LookupError("budget_reached") from None
        outputs.setdefault(case_id, [])
        outputs[case_id].append(raw)
        return raw

    with live_tracking(ledger):
        try:
            yield call, ledger
        finally:
            RECORDINGS.mkdir(parents=True, exist_ok=True)
            for case_id, raws in outputs.items():
                (RECORDINGS / f"{case_id}.json").write_text(json.dumps(
                    {"prompt_fingerprint": fingerprint, "recorded_at": datetime.now(timezone.utc).isoformat(),
                     "outputs": raws}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def evaluate(cases: list[dict], model) -> dict:
    results, skipped = [], []
    for case in cases:
        try:
            results.append(await run_case(case, model))
        except LookupError as exc:
            skipped.append({"id": case["id"], "reason": str(exc).strip("'")})
    return {"summary": vault_golden.summarize(results), "skipped": skipped, "cases": results}


def write_report(report: dict, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "vault_eval.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
    s = report["summary"]

    def pct(block):
        return "—" if block["recall"] is None else f"{block['recall']:.0%} ({block['found']}/{block['expected']})"

    lines = [f"# Vault golden set: {report['mode']}", "",
             f"Cases scored: {s['cases']} · skipped: {len(report['skipped'])}", "",
             f"- Overall recall: {pct(s['overall'])}",
             *[f"- {tier.title()} recall: {pct(block)}" for tier, block in s["by_tier"].items() if block["expected"]],
             f"- Must-not violations: {s['must_not_violations']}",
             f"- Values not in English: {s['not_english_values']}", "",
             "| facet | recall |", "|---|---|",
             *[f"| {facet} | {pct(block)} |" for facet, block in s["by_facet"].items()], "",
             "| language | recall |", "|---|---|",
             *[f"| {lang} | {pct(block)} |" for lang, block in s["by_language"].items()], ""]
    for case in report["cases"]:
        missed = [item["facet"] for item in case["expected"] if not item["found"]]
        if missed or case["must_not_violations"] or case["not_english"]:
            lines.append(f"## {case['id']}")
            if missed:
                lines.append("- Missed: " + ", ".join(missed))
            for violation in case["must_not_violations"]:
                lines.append(f"- Must-not violated ({violation['facet']}): {violation['why']}")
            for value in case["not_english"]:
                lines.append(f"- Not English: {value}")
            for reason in case["extractor_drops"]:
                lines.append(f"- Dropped by extractor: {reason}")
            lines.append("")
    for item in report["skipped"]:
        lines.append(f"- Skipped {item['id']}: {item['reason']}")
    path = directory / "vault_eval.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--live", action="store_true", help="call the real extractor model and save recordings")
    parser.add_argument("--max-cost-usd", type=float, help="required with --live")
    parser.add_argument("--case", action="append", dest="cases", help="run only this case id (repeatable)")
    parser.add_argument("--language", choices=vault_golden.LANGUAGES, help="run only one language")
    parser.add_argument("--report-dir", type=Path, default=None)
    args = parser.parse_args()
    if args.live and not (args.max_cost_usd and args.max_cost_usd > 0):
        parser.error("--live requires --max-cost-usd greater than zero")
    cases = [c for c in vault_golden.load_cases()
             if (not args.cases or c["id"] in args.cases) and (not args.language or c["language"] == args.language)]
    fingerprint = prompt_fingerprint()
    if args.live:
        with live_model(args.max_cost_usd, fingerprint) as (model, ledger):
            report = asyncio.run(evaluate(cases, model))
        report["cost_usd"] = round(ledger.spent, 6)
    else:
        report = asyncio.run(evaluate(cases, recorded_model(fingerprint)))
    report["mode"] = "live" if args.live else "recorded"
    report["prompt_fingerprint"] = fingerprint
    directory = args.report_dir or RESULTS / time.strftime("%Y%m%d-%H%M%S")
    path = write_report(report, directory)
    s = report["summary"]
    print(json.dumps({"mode": report["mode"], "scored": s["cases"], "skipped": len(report["skipped"]),
                      "overall": s["overall"], "by_tier": s["by_tier"],
                      "must_not_violations": s["must_not_violations"],
                      "not_english_values": s["not_english_values"],
                      "cost_usd": report.get("cost_usd"), "report": str(path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
