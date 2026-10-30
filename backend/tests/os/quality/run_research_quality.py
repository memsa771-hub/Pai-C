"""Slice 2 quality gate (spec §9): production research on the 30 programmes, scored against answer key v3.

Runs the production pipeline per programme: the page gateway's `collect`, readings A and B (C when a field has
one valid reading), and `trust.judge`. No plans and no store. Scores each run with the Spike 1 matching rules and
prints both rates and the pass line. The gate passes only if every run reaches the bars in scoring.py
(correct >= 0.95; confirmed >= 0.45, the owners' pilot bar of 2026-10-20, was 0.70).

    # the billed gate (about $1 a run; needs OS_OPENAI_API_KEY and OS_DATABASE_URL for the page cache)
    python -m tests.os.quality.run_research_quality --model openai --runs 3 --min-cycle 2026 --out gate.json

    # offline: the committed Spike 1 page snapshot and a model that finds nothing (free; checks the wiring)
    python -m tests.os.quality.run_research_quality --model test --snapshot --runs 1 --out /tmp/q.json

Do not change the key or the thresholds to pass (plan Task 10 step 4). A failed gate is reported to the owners.
"""

import argparse
import gzip
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path

import yaml

from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.knowledge.profile import load_profile_dir
from app.os.knowledge.programmes import PROGRAMME_SEED, Programme, with_own_pages
from app.os.knowledge.research.pages import Page, PageGateway
from app.os.knowledge.research.readings import build_readers, cost, model_for, run_reading, user_prompt
from app.os.knowledge.research.trust import judge
from app.os.settings import load_settings
from tests.os.quality.scoring import PASS_CONFIRMED, PASS_CORRECT, load_key, score

SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "research" / "spike1-pages-2026-10-19.json.gz"
ROUTE = "germany_master"


def _programmes(only: list[str] | None) -> list[Programme]:
    """The seed's programmes with their own pages (worked out over the whole registry, as the store does)."""
    seed = yaml.safe_load(PROGRAMME_SEED.read_text(encoding="utf-8"))
    every = with_own_pages([
        Programme(ref=ref, route_key=seed["route_key"], university=p["university"], name=p["name"],
                  aliases=tuple(p.get("aliases", ())), start_urls=tuple(p["start_urls"]),
                  official_domains=tuple(p["official_domains"]), status=p.get("status", "active"))
        for ref, p in seed["programmes"].items()])
    return [p for p in every if p.status == "active" and (not only or p.ref in only)]


def _snapshot_fetch():
    data = json.loads(gzip.open(SNAPSHOT).read())["pages"]

    def fetch(url: str) -> Page:
        p = data.get(url)
        if p is None:
            return Page(url=url, blocked="not_in_snapshot")
        return Page(url=url, final_url=p.get("final_url"), http_status=p.get("status"), text=p.get("text") or "",
                    links=tuple(tuple(x) for x in p.get("links") or ()), blocked=p.get("blocked"))

    return fetch


def _test_model():
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    return FunctionModel(lambda messages, info: ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {})]))


def research_one(p: Programme, gateway: PageGateway, fetch, readers, spec, profile, settings, min_cycle: int,
                 billed: bool = True) -> dict:
    """One programme: collect -> A, B (-> C) -> judge, as the os.research workflow does (minus the store)."""
    pages = gateway.collect(p, profile, fetch=fetch)
    prompt = user_prompt(p, pages, profile, min_cycle)
    price = (lambda u: cost(u, settings, spec.tier)) if billed else (lambda u: 0.0)
    readings, spent, errors = {}, 0.0, {}
    for name in ("A", "B"):
        r = run_reading(readers[name], spec, prompt)
        readings[name], errors[name] = r.reading, r.error
        spent += price(r.usage)

    def verdicts():
        return {f.name: judge(f, {n: getattr(x, f.name) for n, x in readings.items() if x is not None}, pages, p,
                              profile, min_cycle) for f in profile.fields}

    got = verdicts()
    one_valid = any(sum(1 for e in v.evidence if not e["reasons"]) == 1 for v in got.values())
    if one_valid and spent < spec.limits.spend_usd_per_programme:
        r = run_reading(readers["C"], spec, prompt)
        readings["C"], errors["C"] = r.reading, r.error
        spent += price(r.usage)
        got = verdicts()
    return {"verdicts": got, "cost_usd": spent, "errors": {k: v for k, v in errors.items() if v},
            "pages": [{"url": x.url, "ok": x.ok, "blocked": x.blocked} for x in pages]}


def run_once(programmes, gateway, fetch, readers, spec, profile, settings, min_cycle, concurrency,
             billed: bool = True) -> dict:
    t0 = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        done = list(pool.map(lambda p: (p.ref, research_one(p, gateway, fetch, readers, spec, profile, settings,
                                                             min_cycle, billed)), programmes))
    results = dict(done)
    fields = [f.name for f in profile.fields]
    key = {ref: row for ref, row in load_key().items() if ref in results}  # the programmes this run researched
    s = score(key, {ref: r["verdicts"] for ref, r in results.items()}, fields)
    passed, fails = s.verdict()
    return {"correct_rate": s.correct_rate, "confirmed_rate": s.confirmed_rate, "scored": s.scored,
            "confirmed": s.confirmed, "correct": s.correct, "passed": passed, "fails": fails,
            "cost_usd": round(sum(r["cost_usd"] for r in results.values()), 4),
            "elapsed_s": round(time.monotonic() - t0, 1), "wrong": s.wrong, "reasons": dict(s.reasons),
            "programmes": {ref: {"cost_usd": r["cost_usd"], "errors": r["errors"], "pages": r["pages"],
                                 "verdicts": {f: asdict(v) for f, v in r["verdicts"].items()}}
                           for ref, r in results.items()}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=["openai", "test"], required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--min-cycle", type=int, default=2026)
    ap.add_argument("--snapshot", action="store_true", help="read the committed Spike 1 pages instead of the web")
    ap.add_argument("--only", nargs="*", help="programme refs (default: all active)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    if args.snapshot:
        settings = load_settings({"OS_DATABASE_URL": "postgresql://unused/x", **_openai_env()})
        gateway, fetch = PageGateway(None, settings.tenant_id, settings), _snapshot_fetch()
    else:
        from app.os.db import make_engine

        settings = load_settings()
        gateway, fetch = PageGateway(make_engine(settings), settings.tenant_id, settings), None
    if args.model == "openai" and not settings.openai_api_key:
        print("OS_OPENAI_API_KEY is not set", file=sys.stderr)
        return 2
    spec, profile = load_agent_spec(AGENT_DIR / "research.v1.yaml"), load_profile_dir()[ROUTE]
    model = model_for(settings, spec.tier) if args.model == "openai" else _test_model()
    readers = build_readers(model, profile, spec)
    programmes = _programmes(args.only)
    runs = []
    for i in range(1, args.runs + 1):
        r = run_once(programmes, gateway, fetch, readers, spec, profile, settings, args.min_cycle, args.concurrency,
                     billed=args.model == "openai")
        runs.append(r)
        print(f"run {i}: correct {r['correct']}/{r['confirmed']} = {r['correct_rate']:.3f}, confirmed "
              f"{r['confirmed']}/{r['scored']} = {r['confirmed_rate']:.3f}, cost ${r['cost_usd']:.2f}, "
              f"{r['elapsed_s']}s -> {'PASS' if r['passed'] else 'FAIL: ' + '; '.join(r['fails'])}")
    gate = bool(runs) and all(r["passed"] for r in runs)
    args.out.write_text(json.dumps({"model": settings.model_cheap if args.model == "openai" else "test",
                                    "min_cycle": args.min_cycle, "snapshot": args.snapshot, "runs": runs,
                                    "gate_passed": gate}, indent=1, default=str), encoding="utf-8")
    print(f"GATE {'PASS' if gate else 'FAIL'}: {sum(r['passed'] for r in runs)}/{len(runs)} runs passed "
          f"(correct >= {PASS_CORRECT} and confirmed >= {PASS_CONFIRMED} in every run). Full results: {args.out}")
    return 0 if gate else 1


def _openai_env() -> dict:
    import os

    key = os.environ.get("OS_OPENAI_API_KEY")
    return {"OS_OPENAI_API_KEY": key} if key else {}


if __name__ == "__main__":
    sys.exit(main())
