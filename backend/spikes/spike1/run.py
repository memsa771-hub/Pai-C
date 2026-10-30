"""Spike 1 run: fetch -> two readings -> trust checks -> score -> JSON report + pass-bar line.

    python -m spikes.spike1.run --model openai --cache /tmp/spike1-pages --out spike1-result.json
    python -m spikes.spike1.run --model test ...   # harness check only, no API calls

`--min-cycle` is the oldest winter-intake year a date or amount may name (SP1-D1, option A):
2026 now (WS 2026/27, the cycle the pages show), 2027 for the re-run once WS 2027/28 is published.
Exit code 1 when the pass bar fails.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from app.os.settings import load_settings
from spikes.spike1.agent import build_agents, openai_model, read, user_prompt
from spikes.spike1.pages import Fetcher, collect
from spikes.spike1.programmes import KEY_PATH, Programme, load_key, load_programmes
from spikes.spike1.score import score
from spikes.spike1.trust import Verdict, judge_programme, needs_third_reading

# Parent §9 prices for gpt-5.4-mini, USD per 1M tokens (checked 2026-10-13).
PRICE_IN, PRICE_CACHED, PRICE_OUT = 0.75, 0.075, 4.50


async def research(programmes: list[Programme], fetcher: Fetcher, model: Model, min_cycle: int,
                   concurrency: int = 4, third: bool = True) -> dict:
    agents = build_agents(model)
    sem = asyncio.Semaphore(concurrency)

    async def one(p: Programme) -> tuple[str, dict]:
        pages = await asyncio.to_thread(collect, fetcher, list(p.start_urls), p.domains)
        prompt = user_prompt(p, pages)
        async with sem:
            ra, rb = await asyncio.gather(read(agents["A"], prompt), read(agents["B"], prompt))
            done = [("A", ra), ("B", rb)]
            if third and needs_third_reading(ra.reading, rb.reading, pages, p.domains):
                done.append(("C", await read(agents["C"], prompt)))
        rc = dict(done).get("C")
        verdicts = judge_programme(ra.reading, rb.reading, pages, p.domains, min_cycle, rc.reading if rc else None)
        return p.ref, {
            "pages": [{"url": x.url, "ok": x.ok, "blocked": x.blocked, "chars": len(x.text)} for x in pages],
            "readings": {n: {"error": r.error, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                             "requests": r.requests, "cache_read_tokens": r.cache_read_tokens, "output": r.reading.model_dump() if r.reading else None}
                         for n, r in done},
            "verdicts": verdicts,
        }

    return dict(await asyncio.gather(*(one(p) for p in programmes)))


def report(results: dict, key: dict, elapsed: float, model_name: str, min_cycle: int) -> dict:
    s = score(key, {ref: r["verdicts"] for ref, r in results.items()})
    passed, fails = s.verdict()
    tin = sum(rd["input_tokens"] for r in results.values() for rd in r["readings"].values())
    tcache = sum(rd.get("cache_read_tokens", 0) for r in results.values() for rd in r["readings"].values())
    tout = sum(rd["output_tokens"] for r in results.values() for rd in r["readings"].values())
    pages = [pg for r in results.values() for pg in r["pages"]]
    return {
        "model": model_name, "min_cycle": min_cycle, "programmes": len(results), "elapsed_s": round(elapsed, 1),
        "scored": s.scored, "confirmed": s.confirmed, "correct": s.correct,
        "correct_rate": round(s.correct_rate, 4), "confirmed_rate": round(s.confirmed_rate, 4),
        "pass": passed, "fails": fails,
        "per_field": {f: dict(c) for f, c in s.per_field.items()},
        "unconfirmed_reasons": dict(s.reasons.most_common()),
        "fabricated_quotes": s.reasons.get("quote_not_on_page", 0),
        "reading_errors": [f"{ref}/{n}: {rd['error']}" for ref, r in results.items()
                           for n, rd in r["readings"].items() if rd["error"]],
        "third_readings": sum("C" in r["readings"] for r in results.values()),
        "pages_read": sum(p["ok"] for p in pages), "pages_blocked": sorted({f"{p['url']} ({p['blocked']})" for p in pages if p["blocked"]}),
        "input_tokens": tin, "cache_read_tokens": tcache, "output_tokens": tout,
        "cost_usd": round((tin - tcache) / 1e6 * PRICE_IN + tcache / 1e6 * PRICE_CACHED + tout / 1e6 * PRICE_OUT, 4),
        "wrong": s.wrong, "extras_for_review": s.extras, "unsettled_for_review": s.unsettled,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=["test", "openai"], required=True)
    ap.add_argument("--cache", type=Path, required=True, help="page cache directory (reused across runs)")
    ap.add_argument("--out", type=Path, required=True, help="full result JSON (verdicts per fact)")
    ap.add_argument("--min-cycle", type=int, default=2026)
    ap.add_argument("--only", nargs="*", help="programme refs to run (default: all 30)")
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--no-third", action="store_true", help="two readings only (runs 1-8)")
    ap.add_argument("--rescore", type=Path, help="score an earlier --out file against the key (no fetch, no model)")
    ap.add_argument("--key", type=Path, default=KEY_PATH, help="answer key to score against (default: the current key)")
    args = ap.parse_args(argv)

    if args.rescore:
        old = json.loads(args.rescore.read_text(encoding="utf-8"))
        results = {ref: {**r, "verdicts": {f: Verdict(**v) for f, v in r["verdicts"].items()}}
                   for ref, r in old["results"].items()}
        key = {ref: row for ref, row in load_key(args.key).items() if ref in results}
        rep = report(results, key, old["report"]["elapsed_s"], old["report"]["model"], old["report"]["min_cycle"])
        args.out.write_text(json.dumps({"report": rep, "results": old["results"]}, indent=2, ensure_ascii=False,
                                       default=str), encoding="utf-8")
        print(json.dumps({k: rep[k] for k in ("scored", "confirmed", "correct", "correct_rate", "confirmed_rate")}))
        print("pass bar: PASS" if rep["pass"] else f"pass bar: FAIL ({'; '.join(rep['fails'])})")
        return 0 if rep["pass"] else 1

    settings = load_settings({"DATABASE_URL": "unused-by-spike1", **os.environ})  # no database here
    if args.model == "openai":
        if not settings.openai_api_key:
            print("OS_OPENAI_API_KEY is not set; the billed run needs the PAI OS key.", file=sys.stderr)
            return 2
        model, model_name = openai_model(settings), settings.model_cheap
    else:
        model, model_name = TestModel(), "test"

    programmes = [p for p in load_programmes() if not args.only or p.ref in args.only]
    t0 = time.monotonic()
    results = asyncio.run(research(programmes, Fetcher(args.cache), model, args.min_cycle, args.concurrency, not args.no_third))
    key = {ref: row for ref, row in load_key(args.key).items() if ref in results}
    rep = report(results, key, time.monotonic() - t0, model_name, args.min_cycle)

    full = {"report": rep, "results": {ref: {**r, "verdicts": {f: asdict(v) for f, v in r["verdicts"].items()}}
                                       for ref, r in results.items()}}
    args.out.write_text(json.dumps(full, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    summary = {k: v for k, v in rep.items() if k not in ("wrong", "extras_for_review", "unsettled_for_review")}
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("pass bar: PASS" if rep["pass"] else f"pass bar: FAIL ({'; '.join(rep['fails'])})")
    return 0 if rep["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
