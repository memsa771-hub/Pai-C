"""Budget-capped live smoke test for one Counselor model.

Replays fixed student messages through the real Counselor prompt and language
policy (one model call per turn, same request shape as the deep turn) and
reports reply quality signals, latency, tokens, cache hits and cost.

    python -m scripts.eval.counselor_smoke --model gpt-6-sol --max-cost-usd 0.5 \
        --messages tests/fixtures/counselor_smoke/messages.json

It never prints the API key. It needs PAI_API_KEY in the environment (.env).
"""

import argparse
import asyncio
import json
import time
import statistics
from datetime import datetime, timezone
from pathlib import Path

from app.config import config
from app.pai_c.deep.polish import (
    contains_blocked_script, has_list, polish_reply, question_count,
)
from app.pai_c.deep.prompts import load_prompt
from app.inference.client import _reasoning_effort_for, create_client, _token_limit_kwarg
from scripts.eval.cost import UsageLedger, BudgetReached, load_prices

PRICES = Path(__file__).with_name("model_prices.json")


def _context(profile: dict) -> str:
    sections = {
        "today": datetime.now(timezone.utc).date().isoformat(),
        "language_policy": json.dumps({
            "blocked_scripts": [s.strip() for s in config.PAI_LANGUAGE_BLOCKED_SCRIPTS.split(",") if s.strip()],
            "replacement": config.PAI_LANGUAGE_BLOCKED_SCRIPT_REPLACEMENT,
            "fallback_reply": config.PAI_COUNSELOR_FALLBACK_REPLY,
        }, ensure_ascii=False),
        "profile": json.dumps(profile, ensure_ascii=False),
        "notebook": "{}",
        "memory": "{}",
        "journey": json.dumps({"stage": "FOUNDATION"}),
    }
    return "<context>\n" + "\n".join(f"<{k}>{v}</{k}>" for k, v in sections.items()) + "\n</context>"


def _cost(price: dict, usage: dict) -> float:
    fresh = usage["input_tokens"] - usage["cached_input_tokens"]
    return (fresh * price["input"] + usage["cached_input_tokens"] * price["cached_input"]
            + usage["output_tokens"] * price["output"]) / 1_000_000


async def run(args) -> dict:
    prices = load_prices(PRICES)
    if args.max_cost_usd <= 0:
        raise ValueError("positive budget required")
    ledger = UsageLedger(prices, args.max_cost_usd)
    price = prices.get(args.model)
    if not price or not (price.get("input") or price.get("output")):
        raise SystemExit(f"No price for {args.model} in {PRICES.name}; add it before a live run.")
    if price.get("verify_before_live"):
        raise ValueError("price verification required before live")
    fixture = json.loads(Path(args.messages).read_text(encoding="utf-8"))
    system = load_prompt("counselor") + "\n\n" + _context(fixture.get("profile", {}))
    client = create_client(config.PAI_API_KEY, base_url=config.PAI_BASE_URL).with_options(max_retries=0)
    effort = _reasoning_effort_for(args.model, args.reasoning_effort, has_tools=False)
    history: list[dict] = []
    turns, spent = [], 0.0
    for number, student in enumerate(fixture["messages"], start=1):
        messages = [{"role": "system", "content": system},
                    *history[-args.history_size:], {"role": "user", "content": student}]
        kwargs = {"model": args.model, "messages": messages,
                  "response_format": {"type": "json_object"},
                  _token_limit_kwarg(args.model): getattr(args, "output_limit", 1024)}
        if effort:
            kwargs["reasoning_effort"] = effort
        try:
            reservation = ledger.reserve(args.model, messages, getattr(args, "output_limit", 1024))
        except BudgetReached:
            break
        started = time.monotonic()
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception:
            break  # Retain ambiguous-call reservation; never retry.
        elapsed = int((time.monotonic() - started) * 1000)
        raw = response.choices[0].message.content or ""
        u = response.usage
        details = getattr(u, "prompt_tokens_details", None)
        usage = {"input_tokens": u.prompt_tokens, "output_tokens": u.completion_tokens,
                 "cached_input_tokens": getattr(details, "cached_tokens", 0) or 0}
        try:
            record = ledger.settle(u, args.model, "counselor", reservation)
        except BudgetReached:
            break
        usage["reasoning_tokens"] = record["reasoning"]
        cost = record["cost_usd"]
        spent += cost
        try:
            parsed = json.loads(raw)
            reply, action = str(parsed.get("reply", "")), parsed.get("action") or {}
            valid = True
        except ValueError:
            reply, action, valid = raw, {}, False
        polished = polish_reply(reply)
        turns.append({
            "turn": number, "student": student, "reply": polished, "action": action,
            "valid_json": valid, "questions_before_polish": question_count(reply),
            "has_list": has_list(reply), "words": len(polished.split()),
            "blocked_script": contains_blocked_script(reply, config.PAI_LANGUAGE_BLOCKED_SCRIPTS),
            "ms": elapsed, "usage": usage, "usd": round(cost, 6),
        })
        print(f"[{number}] {elapsed} ms ${cost:.4f}\n  S: {student}\n  C: {polished}\n  action: {action}")
        history += [{"role": "user", "content": student}, {"role": "assistant", "content": polished}]
        if spent >= args.max_cost_usd:
            print(f"Budget reached (${spent:.4f}); stopping.")
            break
    latencies = sorted(t["ms"] for t in turns)
    input_total = sum(t["usage"]["input_tokens"] for t in turns)
    summary = {
        "model": args.model, "reasoning_effort": effort, "turns": len(turns),
        "total_usd": round(spent, 4),
        "p50_ms": statistics.median(latencies) if latencies else None,
        "max_ms": latencies[-1] if latencies else None,
        "p95_ms": round(statistics.quantiles(latencies, n=100, method="inclusive")[94], 1) if len(latencies)>1 else (latencies[0] if latencies else None),
        "reserved_usd": ledger.reserved_usd,
        "status": "complete" if len(turns)==len(fixture["messages"]) else "partial",
        "cache_hit_ratio": round(sum(t["usage"]["cached_input_tokens"] for t in turns) / input_total, 3)
        if input_total else 0,
        "invalid_json": sum(not t["valid_json"] for t in turns),
        "multi_question_replies": sum(t["questions_before_polish"] > 1 for t in turns),
        "list_replies": sum(t["has_list"] for t in turns),
        "blocked_script_replies": sum(t["blocked_script"] for t in turns),
        "max_words": max((t["words"] for t in turns), default=0),
    }
    await client.close()
    return {"summary": summary, "turns": turns}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--messages", required=True, help="JSON file: {profile, messages: [...]}")
    parser.add_argument("--max-cost-usd", type=float, required=True)
    parser.add_argument("--reasoning-effort", default=config.PAI_COUNSELOR_REASONING_EFFORT)
    parser.add_argument("--history-size", type=int, default=config.PAI_COUNSELOR_HISTORY_SIZE)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--output-limit", type=int, default=1024)
    args = parser.parse_args()
    result = asyncio.run(run(args))
    print(json.dumps(result["summary"], indent=2))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
