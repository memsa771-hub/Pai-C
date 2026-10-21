"""Spike 2: the Slice 3 quality gate (spec §8 test 9, §9; plan Task 10).

Runs the production document pipeline on each file of a set: `check_upload`, `prepare`, the reader (mode `whole`
or `tiles`) and `validate`, then the cross-checks per person. No database. Scores the readings against the set's
key (doc_scoring.py) and prints **only rates and counts, never a value**. The --out file holds the same.

    # the billed gate (owner's go-ahead and a verified key; about $1-3 a run; needs OS_OPENAI_API_KEY)
    python -m tests.os.quality.run_document_quality --model openai --set real --mode whole --runs 2 --out real-whole.json
    python -m tests.os.quality.run_document_quality --model openai --set real --mode tiles --runs 2 --out real-tiles.json
    python -m tests.os.quality.run_document_quality --model openai --set sample --mode whole --runs 1 --out sample.json

    # offline (free): a test model that answers each file from the key; checks the wiring, scoring and cross-checks
    python -m tests.os.quality.run_document_quality --model test --set sample --mode whole --runs 1 --out /tmp/s.json

The real set never enters the repo: it defaults to ~/spike2-docs/docs and ~/spike2-docs/answer_key.yaml, and a
billed run on it needs `verified: true` in the key (the owner checked it). Do not change the key or the bar to pass.
A failed gate is reported to the owners.

The gate (spec §9): on the real set, the chosen mode reaches >= 0.90 of fields correct in every run. On the sample
set, every planted finding is caught, and no consistent bundle gets a mismatch or more than one variant flag.
"""

import argparse
import contextvars
import json
import sys
import time
from datetime import date
from pathlib import Path

from app.os.agents.spec import AGENT_DIR, AgentSpec, load_agent_spec
from app.os.documents.checks import cross_check, load_name_variants
from app.os.documents.intake import UploadError, check_upload, prepare
from app.os.documents.reader import build_readers, read_document
from app.os.documents.types import load_document_types
from app.os.documents.validators import validate
from app.os.knowledge.research.readings import cost, model_for
from app.os.settings import load_settings
from tests.os.quality.doc_scoring import PASS_CORRECT, load_doc_key, score
from tests.os.quality.make_sample_docs import KEY_NAME, SAMPLES

REAL_DOCS = Path.home() / "spike2-docs" / "docs"
REAL_KEY = Path.home() / "spike2-docs" / "answer_key.yaml"
_CURRENT: contextvars.ContextVar[dict] = contextvars.ContextVar("current_key_fields")


def _test_model():
    """Answers each file with its key values (set by the runner for the file being read)."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    def answer(messages, info):
        entry = _CURRENT.get({})
        args = {k: v for k, v in entry.get("fields", {}).items() if v is not None}
        args["detected_type"] = entry.get("type")
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    return FunctionModel(answer)


def read_one(path: Path, entry: dict, readers, spec: AgentSpec, types, settings, billed: bool) -> dict:
    """One file through intake, the reader and the validators. Returns values (or None), checks, cost, error."""
    data = path.read_bytes()
    t = types[entry["type"]]
    try:
        parts = prepare(data, check_upload(path.name, data))
    except UploadError:
        return {"values": None, "checks": {}, "cost_usd": 0.0, "error": "unreadable", "detected": None}
    token = _CURRENT.set(entry)
    try:
        r = read_document(readers[t.key], spec, t, parts)
    finally:
        _CURRENT.reset(token)
    checks = validate(t, r.values, date.today()) if r.values is not None else {}
    return {"values": r.values, "checks": checks, "detected": r.detected_type,
            "cost_usd": cost(r.usage, settings, spec.tier) if billed else 0.0,
            "error": None if r.error is None else r.error.split(":", 1)[0]}


def findings_by_person(key_docs: dict, results: dict, types, variants) -> dict[str, list[dict]]:
    """The cross-check findings per person over the base documents (not the rotated or low-resolution copies)."""
    people: dict[str, list] = {}
    for i, (name, entry) in enumerate(sorted(key_docs.items())):
        values = results.get(name, {}).get("values")
        if entry.get("person") and not entry.get("variant_of") and values is not None:
            people.setdefault(entry["person"], []).append((i, types[entry["type"]], values))
    return {p: [{"kind": f.kind, "field": f.field} for f in cross_check(docs, variants)]
            for p, docs in sorted(people.items())}


def bundle_verdict(expect: dict, found: dict[str, list[dict]]) -> tuple[bool, list[str]]:
    """Every planted finding caught; a consistent bundle has no mismatch and at most one variant flag."""
    fails = []
    for b, spec in sorted(expect.items()):
        got, want = found.get(b, []), spec.get("expect", [])
        for w in want:
            fields = [g for g in got if g["field"] == w["field"]]
            ok = any(g["kind"] == "mismatch" for g in fields) if w["kind"] == "mismatch" else bool(fields)
            if not ok:
                fails.append(f"{b}: planted {w['kind']} on {w['field']} not caught")
        if not want:
            if any(g["kind"] == "mismatch" for g in got):
                fails.append(f"{b}: consistent bundle got a mismatch")
            if sum(g["kind"] == "variant" for g in got) > 1:
                fails.append(f"{b}: consistent bundle got more than one variant flag")
    return not fails, fails


def run_once(docs_dir: Path, key: dict, readers, spec, types, variants, settings, billed: bool) -> dict:
    t0 = time.monotonic()
    key_docs = {n: e for n, e in key["documents"].items() if (docs_dir / n).is_file()}
    results = {n: read_one(docs_dir / n, e, readers, spec, types, settings, billed) for n, e in sorted(key_docs.items())}
    s = score(key_docs, {n: r["values"] for n, r in results.items()}, types)
    mismatched_type = sum(1 for n, r in results.items() if r["detected"] and r["detected"] != key_docs[n]["type"]
                          and r["detected"].replace(" ", "_").casefold() != key_docs[n]["type"])
    out = {"files": len(key_docs), "missing_files": len(set(key["documents"]) - set(key_docs)),  # a count: real file names may hold names
           "correct": s.correct, "scored": s.scored, "invented": s.invented, "correct_rate": round(s.rate, 4),
           "per_type": s.type_rates(), "per_field": s.field_counts(), "failed_readings": sum(r["values"] is None for r in results.values()),
           "check_failed_fields": sum(1 for r in results.values() for c, _ in r["checks"].values()
                                      if c == "check_failed"),
           "detected_type_differs": mismatched_type,
           "cost_usd": round(sum(r["cost_usd"] for r in results.values()), 4),
           "elapsed_s": round(time.monotonic() - t0, 1)}
    if key.get("bundles"):
        found = findings_by_person(key_docs, results, types, variants)
        ok, fails = bundle_verdict(key["bundles"], found)
        out.update({"bundles_passed": ok, "bundle_fails": fails,
                    "findings_per_bundle": {b: [f"{f['kind']}:{f['field']}" for f in fs] for b, fs in found.items()}})
    out["passed"] = (out["correct_rate"] >= PASS_CORRECT if not key.get("bundles")
                     else out["correct_rate"] >= PASS_CORRECT and out["bundles_passed"])
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=["openai", "test"], required=True)
    ap.add_argument("--set", choices=["real", "sample"], required=True, dest="which")
    ap.add_argument("--docs", type=Path, help="the folder of files (default: by --set)")
    ap.add_argument("--key", type=Path, help="the answer key (default: by --set)")
    ap.add_argument("--mode", choices=["whole", "tiles"], required=True)
    ap.add_argument("--tier", choices=["cheap", "strong"], default=None,
                    help="the model tier (default: the agent spec's, cheap)")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    docs_dir = args.docs or (REAL_DOCS if args.which == "real" else SAMPLES)
    key_path = args.key or (REAL_KEY if args.which == "real" else SAMPLES / KEY_NAME)
    if not docs_dir.is_dir() or not key_path.is_file():
        print(f"the {args.which} set is not here (files: {docs_dir}, key: {key_path})", file=sys.stderr)
        return 2
    key = load_doc_key(key_path)
    import os

    passed = {k: v for k, v in os.environ.items() if k == "OS_OPENAI_API_KEY" or k.startswith(("OS_PRICE_", "OS_MODEL_"))}
    settings = load_settings({"OS_DATABASE_URL": "postgresql://unused/x", **passed})
    if args.model == "openai":
        if not settings.openai_api_key:
            print("OS_OPENAI_API_KEY is not set", file=sys.stderr)
            return 2
        if key.get("verified") is not True:
            print("the answer key is not verified (`verified: true`): no billed run on it", file=sys.stderr)
            return 2
    spec = load_agent_spec(AGENT_DIR / "documents.v1.yaml")
    spec = AgentSpec.model_validate({**spec.model_dump(), "mode": args.mode, "tier": args.tier or spec.tier})
    if args.model == "openai":
        prices = {"in": settings.price_strong_in, "cached": settings.price_strong_cached,
                  "out": settings.price_strong_out} if spec.tier == "strong" else {
                  "in": settings.price_cheap_in, "cached": settings.price_cheap_cached, "out": settings.price_cheap_out}
        unknown = [f"OS_PRICE_{spec.tier.upper()}_{k.upper()}" for k, v in prices.items() if v is None]
        if unknown:
            print(f"the {spec.tier} tier's list price is not set: {', '.join(unknown)} (USD per 1M tokens)",
                  file=sys.stderr)
            return 2
    types, variants = load_document_types(), load_name_variants()
    model = model_for(settings, spec.tier) if args.model == "openai" else _test_model()
    readers = build_readers(model, types, spec)
    runs = []
    for i in range(1, args.runs + 1):
        r = run_once(docs_dir, key, readers, spec, types, variants, settings, billed=args.model == "openai")
        runs.append(r)
        extra = "" if "bundles_passed" not in r else (
            f", bundles {'ok' if r['bundles_passed'] else 'FAIL: ' + '; '.join(r['bundle_fails'])}")
        print(f"run {i} ({args.mode}, {spec.tier}): correct {r['correct']}/{r['scored']} = {r['correct_rate']:.3f}, "
              f"invented {r['invented']}, failed readings {r['failed_readings']}{extra}, cost ${r['cost_usd']:.2f}, "
              f"{r['elapsed_s']}s -> {'PASS' if r['passed'] else 'FAIL'}")
        print(f"  per type: {r['per_type']}")
        print("  per field (worst first; names and counts only):")
        worst = sorted(r["per_field"].items(), key=lambda kv: (kv[1]["correct"] - sum(kv[1].values()), kv[0]))
        for name, c in worst:
            n = sum(c.values())
            print(f"    {name}: correct {c['correct']}/{n}, wrong {c['wrong']}, missed {c['missed']}, "
                  f"invented {c['invented']}")
    gate = bool(runs) and all(r["passed"] for r in runs)
    model_name = settings.model_strong if spec.tier == "strong" else settings.model_cheap
    args.out.write_text(json.dumps({"set": args.which, "mode": args.mode, "tier": spec.tier,
                                    "model": model_name if args.model == "openai" else "test",
                                    "runs": runs, "gate_passed": gate}, indent=1), encoding="utf-8")
    print(f"GATE {'PASS' if gate else 'FAIL'} ({args.which}, {args.mode}): {sum(r['passed'] for r in runs)}/"
          f"{len(runs)} runs passed (correct >= {PASS_CORRECT} in every run"
          f"{'; planted findings caught' if key.get('bundles') else ''}). Rates only: {args.out}")
    return 0 if gate else 1


if __name__ == "__main__":
    sys.exit(main())
