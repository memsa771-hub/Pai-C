"""Extraction golden set: what the Vault shows after a student's own words.

Each case in tests/fixtures/extraction/*.json holds the student's messages, a
fixed extractor output for them, and what the Vault view must and must not
show afterwards (labels, never codes). The offline test
(tests/test_extraction_golden.py) feeds the fixed output through the real
normalizer, candidate store and reconciler; this script runs the same messages
through the REAL extractor model and scores the Vault the same way.

Modes:
  --live     call the configured extractor model, never above --cap-usd, and
             save each case's raw outputs to the recordings folder
  --replay   score the saved recordings (no model calls, no cost)

Nothing runs without one of them: a live run costs money and must be asked for.

Usage:
  python -m scripts.eval_extraction --replay
  python -m scripts.eval_extraction --live --cap-usd 5
  python -m scripts.eval_extraction --live --case ru-budget-lakh --min-recall 0.9
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "tests" / "fixtures" / "extraction"
RECORDINGS = CASES / "recordings"
MODEL_COSTS = ROOT / "app" / "pai_c" / "policy" / "model_costs.json"
LANGUAGES = ("roman_ur", "ur", "en")
KINDS = ("fact", "record", "item")
LEVELS = ("inferred", "stated", "shown", "confirmed")
CHARS_PER_TOKEN = 4
# What one extractor reply is assumed to cost in output before it arrives, so
# the call that would cross the cap is never made.
OUTPUT_RESERVE_TOKENS = 1500
_PLACEHOLDER = re.compile(r"^@(?:(item):)?([a-z_.]+)\[(\d+)\]$")


# ---- cases -----------------------------------------------------------------

def validate_case(case: dict) -> None:
    """A malformed case would score silently wrong; refuse it by name."""
    for name in ("id", "language", "student_messages", "extractor_output", "expected_vault"):
        if name not in case:
            raise ValueError(f"{case.get('id')}: missing {name}")
    if case["language"] not in LANGUAGES:
        raise ValueError(f"{case['id']}: language {case['language']!r}")
    messages = case["student_messages"]
    if not messages or not all(isinstance(m, str) and m.strip() for m in messages):
        raise ValueError(f"{case['id']}: student_messages")
    if len(outputs_for(case)) != len(messages):
        raise ValueError(f"{case['id']}: one extractor_output per student message")
    for spec in case["expected_vault"]:
        if spec.get("kind") not in KINDS or not spec.get("type"):
            raise ValueError(f"{case['id']}: expected kind/type {spec}")
        if spec.get("evidence_level", "stated") not in LEVELS:
            raise ValueError(f"{case['id']}: evidence_level {spec}")
    for spec in case.get("must_not", []):
        if not spec.get("type") or not spec.get("why"):
            raise ValueError(f"{case['id']}: must_not needs type and why")


def outputs_for(case: dict) -> list[dict]:
    """A one-message case may give its extractor output as one object."""
    output = case["extractor_output"]
    return output if isinstance(output, list) else [output]


def load_cases() -> list[dict]:
    cases = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(CASES.glob("*.json"))]
    for case in cases:
        validate_case(case)
    return cases


# ---- the Vault as the student sees it ---------------------------------------

def vault_entries(db, workspace_id: str) -> tuple[list[dict], int]:
    """Every entry of the Vault view (Details and Story), and the open conflict cards."""
    from app.memory.vault_view import VaultView
    view = VaultView(db).build(workspace_id)
    entries = [e for section in view["details"].values() for e in section["entries"]]
    entries += [e for card in view["story"] for e in card["entries"]]
    return entries, len(view["conflicts"])


def entry_matches(spec: dict, entry: dict) -> bool:
    """Labels, never codes: a spec matches on the entry's display line."""
    if entry["type"] != spec["type"] or (spec.get("kind") and entry["kind"] != spec["kind"]):
        return False
    display = (entry.get("display") or "").casefold()
    if not all(part.casefold() in display for part in spec.get("display", ())):
        return False
    if spec.get("display_any") and not any(part.casefold() in display for part in spec["display_any"]):
        return False
    return "evidence_level" not in spec or entry["level"] == spec["evidence_level"]


ARABIC_SCRIPT = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
RAW_CODE = re.compile(r"\b[a-z]+_[a-z_]+\b")


def score_case(case: dict, entries: list[dict], conflicts: int) -> dict:
    """Expected entries found (each entry counts for one spec), must-nots hit,
    and the language rules every entry keeps: English, and no raw codes."""
    unused = list(entries)
    expected = []
    for spec in case["expected_vault"]:
        hit = next((e for e in unused if entry_matches(spec, e)), None)
        if hit is not None:
            unused.remove(hit)
        expected.append({**spec, "found": hit is not None,
                         "seen": None if hit else [e["display"] for e in entries if e["type"] == spec["type"]]})
    violations = []
    for spec in case.get("must_not", []):
        bad = [e["display"] for e in entries if e["type"] == spec["type"]
               and all(p.casefold() in (e.get("display") or "").casefold() for p in spec.get("display", ()))]
        if bad:
            violations.append({"type": spec["type"], "why": spec["why"], "seen": bad})
    for type_key, count in (case.get("expected_counts") or {}).items():
        seen = [e["display"] for e in entries if e["type"] == type_key]
        if len(seen) != count:
            violations.append({"type": type_key, "why": f"expected {count} entries", "seen": seen})
    if "expected_conflicts" in case and conflicts != case["expected_conflicts"]:
        violations.append({"type": "conflicts", "why": f"expected {case['expected_conflicts']} open conflicts",
                           "seen": [conflicts]})
    for entry in entries:
        display = entry.get("display") or ""
        if ARABIC_SCRIPT.search(display) or RAW_CODE.search(display):
            violations.append({"type": entry["type"], "why": "not English words", "seen": [display]})
    # Precision is over the types the case speaks about: an extra entry of a
    # type nobody asked about is not this case's concern.
    scored = {spec["type"] for spec in case["expected_vault"]} | {spec["type"] for spec in case.get("must_not", [])}
    produced = [e for e in entries if e["type"] in scored]
    return {"id": case["id"], "language": case["language"], "expected": expected, "violations": violations,
            "produced": [{"type": e["type"], "display": e["display"], "level": e["level"]} for e in produced]}


def summarize(results: list[dict]) -> dict:
    by_type: dict[str, dict] = {}

    def block(name):
        return by_type.setdefault(name, {"expected": 0, "found": 0, "produced": 0})

    core = {"expected": 0, "found": 0}
    for result in results:
        for item in result["expected"]:
            row = block(item["type"])
            row["expected"] += 1
            row["found"] += item["found"]
            if item.get("core"):
                core["expected"] += 1
                core["found"] += item["found"]
        for entry in result["produced"]:
            block(entry["type"])["produced"] += 1

    def rates(row):
        recall = row["found"] / row["expected"] if row["expected"] else None
        precision = row["found"] / row["produced"] if row["produced"] else None
        return {**row, "recall": recall, "precision": precision}

    total = {k: sum(r[k] for r in by_type.values()) for k in ("expected", "found", "produced")}
    return {"cases": len(results), "overall": rates(total),
            "core_recall": core["found"] / core["expected"] if core["expected"] else None,
            "by_type": {name: rates(row) for name, row in sorted(by_type.items())},
            "violations": sum(len(r["violations"]) for r in results)}


# ---- running a case ---------------------------------------------------------

def _resolve_placeholders(node, student):
    """A fixed output names an earlier record or item as "@education[0]" or
    "@item:strength[0]" (the n-th by creation), since its real id exists only
    once the earlier message has been stored."""
    if isinstance(node, dict):
        return {k: _resolve_placeholders(v, student) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_placeholders(v, student) for v in node]
    match = _PLACEHOLDER.match(node) if isinstance(node, str) else None
    if not match:
        return node
    from sqlalchemy import select
    from app.memory.student_records import ENTITY_MODELS
    from app.models import VaultItem
    is_item, kind, index = match.group(1), match.group(2), int(match.group(3))
    with student.factory() as db:
        if is_item:
            rows = db.scalars(select(VaultItem).where(VaultItem.workspace_id == student.workspace_id,
                                                      VaultItem.item_type == kind)
                              .order_by(VaultItem.created_at)).all()
        else:
            model = ENTITY_MODELS[kind]
            rows = db.scalars(select(model).where(model.workspace_id == student.workspace_id)
                              .order_by(model.created_at)).all()
        return str(rows[index].id)


async def run_case(case: dict, model) -> dict:
    """Post each student message and run the persisted extract and reconcile
    jobs, as a turn does; `model(case, index, kwargs, student)` is the
    extractor's raw reply to message `index`."""
    from app.memory import extractor, handlers
    from app.memory.index import NullMemoryIndex
    from scripts.eval_vault import VaultSession
    index = {"value": 0}
    with VaultSession() as student:
        async def call(**kwargs):
            return await model(case, index["value"], kwargs, student)

        with patch.object(extractor, "chat_completion", call), \
                patch.object(extractor, "_model_config", return_value=_model_config()),                 patch.object(handlers, "get_memory_index", NullMemoryIndex):
            # The Vault is what is scored; recall indexing (and a vector
            # server) has no part in it.
            for position, text in enumerate(case["student_messages"]):
                index["value"] = position
                student.student_message(text)
                await student.extract_and_reconcile()
        with student.factory() as db:
            entries, conflicts = vault_entries(db, student.workspace_id)
    return score_case(case, entries, conflicts)


def _model_config():
    """The real extractor config when a key is present; a stand-in otherwise,
    so offline runs never need a key (the model call itself is replaced)."""
    from app.memory import extractor
    api_key, model, base_url = extractor._model_config()
    return (api_key or "offline", model, base_url)


async def fixed_model(case, index, kwargs, student):
    return json.dumps(_resolve_placeholders(outputs_for(case)[index], student), ensure_ascii=False)


def prompt_fingerprint() -> str:
    from scripts.eval_vault import prompt_fingerprint as fingerprint
    return fingerprint()


def recorded_model(fingerprint: str):
    """Replays saved outputs; a missing or stale recording is reported, never faked."""
    async def call(case, index, kwargs, student):
        path = RECORDINGS / f"{case['id']}.json"
        if not path.exists():
            raise LookupError("not_recorded")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("prompt_fingerprint") != fingerprint:
            raise LookupError("stale_recording")
        return data["outputs"][index]
    return call


def model_rates(model: str, usd_per_million: float) -> tuple[float, float]:
    """(input, output) USD per million tokens: model_costs.json's row for the
    model (or its default row) when the file exists, else the flag's rate."""
    if MODEL_COSTS.exists():
        data = json.loads(MODEL_COSTS.read_text(encoding="utf-8"))
        for table in (data.get("models"), data.get("usd_per_million_tokens"), data):
            row = (table.get(model) or table.get("default")) if isinstance(table, dict) else None
            if isinstance(row, (int, float)):
                return float(row), float(row)
            if isinstance(row, dict) and isinstance(row.get("input"), (int, float)):
                return float(row["input"]), float(row.get("output", row["input"]))
    return usd_per_million, usd_per_million


class LiveModel:
    """The real extractor under a hard cap; tokens are estimated from
    characters, so the cap holds even before usage is reported."""

    def __init__(self, cap_usd: float, usd_per_million: float, fingerprint: str):
        from app.memory import extractor
        self.real = extractor.chat_completion
        self.cap, self.spent, self.fingerprint = cap_usd, 0.0, fingerprint
        self.model = extractor._model_config()[1]
        self.rate_in, self.rate_out = model_rates(self.model, usd_per_million)
        self.outputs: dict[str, list[str]] = {}

    def _usd(self, chars: int, rate: float) -> float:
        return chars / CHARS_PER_TOKEN * rate / 1e6

    async def __call__(self, case, index, kwargs, student):
        sent = len(kwargs.get("system_prompt") or "") + sum(len(m.get("content") or "")
                                                            for m in kwargs.get("messages", []))
        projected = self.spent + self._usd(sent, self.rate_in) + OUTPUT_RESERVE_TOKENS * self.rate_out / 1e6
        if projected > self.cap:
            raise LookupError("budget_reached")
        raw = await self.real(**kwargs)
        self.spent += self._usd(sent, self.rate_in) + self._usd(len(raw or ""), self.rate_out)
        self.outputs.setdefault(case["id"], []).append(raw)
        return raw

    def save(self) -> None:
        RECORDINGS.mkdir(parents=True, exist_ok=True)
        for case_id, raws in self.outputs.items():
            (RECORDINGS / f"{case_id}.json").write_text(json.dumps(
                {"prompt_fingerprint": self.fingerprint, "model": self.model,
                 "recorded_at": datetime.now(timezone.utc).isoformat(), "outputs": raws},
                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


async def evaluate(cases: list[dict], model) -> dict:
    results, skipped = [], []
    for case in cases:
        try:
            results.append(await run_case(case, model))
        except LookupError as exc:
            skipped.append({"id": case["id"], "reason": str(exc).strip("'")})
    return {"summary": summarize(results), "skipped": skipped, "cases": results}


def _pct(value) -> str:
    return "-" if value is None else f"{value:.0%}"


def print_report(report: dict) -> None:
    s = report["summary"]
    print(f"Extraction golden set ({report['mode']}): {s['cases']} scored, {len(report['skipped'])} skipped")
    print(f"{'type':34} {'recall':>8} {'precision':>10}")
    for name, row in s["by_type"].items():
        print(f"{name:34} {_pct(row['recall']):>8} {_pct(row['precision']):>10}")
    print(f"{'overall':34} {_pct(s['overall']['recall']):>8} {_pct(s['overall']['precision']):>10}")
    print(f"core recall {_pct(s['core_recall'])}, violations {s['violations']}")
    for case in report["cases"]:
        for item in case["expected"]:
            if not item["found"]:
                print(f"  missed {case['id']}: {item['type']} {item.get('display') or item.get('display_any')}"
                      f" (saw {item['seen']})")
        for violation in case["violations"]:
            print(f"  violated {case['id']}: {violation['type']}: {violation['why']} {violation['seen']}")
    for item in report["skipped"]:
        print(f"  skipped {item['id']}: {item['reason']}")
    if "cost_usd" in report:
        print(f"estimated cost ${report['cost_usd']:.4f}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--live", action="store_true", help="call the real extractor model (costs money)")
    mode.add_argument("--replay", action="store_true", help="score saved recordings, no model calls")
    parser.add_argument("--cap-usd", type=float, default=5.0, help="hard spend cap for --live (default 5)")
    parser.add_argument("--usd-per-million", type=float, default=2.0,
                        help="token rate when model_costs.json does not list the model")
    parser.add_argument("--min-recall", type=float, default=0.9, help="exit non-zero below this core recall")
    parser.add_argument("--case", action="append", dest="cases", help="only this case id (repeatable)")
    args = parser.parse_args(argv)
    if not (args.live or args.replay):
        parser.error("refusing to run: pass --live (real model calls, capped by --cap-usd) or --replay")
    if args.live and not args.cap_usd > 0:
        parser.error("--cap-usd must be greater than zero")
    cases = [c for c in load_cases() if not args.cases or c["id"] in args.cases]
    fingerprint = prompt_fingerprint()
    if args.live:
        from app.config import config
        if not (getattr(config, "MEMORY_EXTRACTOR_API_KEY", "") or config.PAI_API_KEY):
            parser.error("--live needs the extractor model key in the environment")
        live = LiveModel(args.cap_usd, args.usd_per_million, fingerprint)
        try:
            report = asyncio.run(evaluate(cases, live))
        finally:
            live.save()
        report["cost_usd"] = live.spent
    else:
        report = asyncio.run(evaluate(cases, recorded_model(fingerprint)))
    report["mode"] = "live" if args.live else "replay"
    print_report(report)
    recall = report["summary"]["core_recall"]
    return 0 if recall is not None and recall >= args.min_recall else 1


if __name__ == "__main__":
    sys.exit(main())
