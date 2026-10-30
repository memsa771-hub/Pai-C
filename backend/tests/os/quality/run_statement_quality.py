"""Spike 4: the Slice 5 quality gate (spec S5-D11, §9; plan Task 10).

Drafts an SOP and a CV for each persona of a set with the production Writer, facts check and Critic (the os.statement
loop, without the database), then checks them. Prints **only rates and counts**; the --out file holds the same.

    # offline (free): a test model that writes from the persona's own answers and plants each trap
    python -m tests.os.quality.run_statement_quality --model test --set fictional --runs 1 --out /tmp/s5.json

    # billed, with the owners' OK (needs OS_OPENAI_API_KEY and the strong tier's prices)
    python -m tests.os.quality.run_statement_quality --model openai --set fictional --runs 1 --out fictional.json
    python -m tests.os.quality.run_statement_quality --model openai --set roleplay --runs 1 --out roleplay.json
    python -m tests.os.quality.run_statement_quality --model openai --set roleplay --score --out roleplay-score.json

Fictional set (automatic): every planted invention that reaches a draft is flagged, every draft keeps its limit (or
is labelled over it), and no persona's distinctive phrases appear in another persona's draft.

Role-played set: owners and colleagues play students. It never enters the repo; it defaults to ~/spike5-roleplay/
(personas.yaml, same shape). The runner writes each draft to <dir>/drafts/ for the judges, who rate each one in
<dir>/ratings.yaml: {persona_id: {sop: {usable_after_one_edit: bool, invented_facts: int}, cv: {...}}}. `--score`
reads the ratings back. The gate (Q3): at least 8 of 10 usable after one edit for each kind, and 0 invented facts.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import yaml

from app.os.agents.spec import AGENT_DIR, load_agent_spec
from app.os.knowledge.research.readings import cost, model_for
from app.os.settings import load_settings
from app.os.statements.agents import Inputs, build_agents, review, write
from app.os.statements.config import load_statement_configs
from app.os.statements.facts_check import unsupported
from app.os.statements.rules import Rules
from app.os.statements.run import MAX_REVISIONS, sources

FICTIONAL = Path(__file__).parents[1] / "fixtures" / "statements"
ROLEPLAY = Path.home() / "spike5-roleplay"
KINDS = ("sop", "cv")
GATE_USABLE = 8  # of 10, for each kind (Q3)


def load_set(directory: Path) -> dict:
    data = yaml.safe_load((directory / "personas.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(data.get("personas"), list) or not data.get("route"):
        raise ValueError("personas.yaml needs `route` and a `personas` list")
    return data


def inputs_of(persona: dict, cfg, kind: str) -> Inputs:
    answers = {}
    for q in cfg.questions:
        a = (persona["answers"].get(q.id) or "").strip()
        if a:
            answers[q.prompt] = a
    allowed = set(cfg.kinds[kind].profile_keys)
    profile = {k: v for k, v in persona.get("profile", {}).items() if k in allowed}
    rules = Rules(True, cfg.kinds[kind].default_words, None, None, "default")
    return Inputs(kind, answers, profile, rules, list(cfg.kinds[kind].rubric.criteria), list(cfg.allowed_names))


def _test_model():
    """Writer: the persona's own answers, plus one sentence per planted trap. Critic: always satisfied. A redraft
    (asked to remove flags) drops the planted sentences, as a good Writer would."""
    from pydantic_ai.messages import ModelResponse, ToolCallPart, UserPromptPart
    from pydantic_ai.models.function import FunctionModel

    def answer(messages, info):
        system = " ".join(p.content for m in messages for p in m.parts if p.part_kind == "system-prompt")
        prompt = " ".join(str(p.content) for m in messages for p in m.parts if isinstance(p, UserPromptPart))
        if "You co-write" not in system:
            return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {
                "scores": {"Motivation": 4}, "fixes": [], "follow_ups": [], "ok": True})])
        body = [line for line in prompt.split("\n") if line and not line.startswith(("<<<", "Write ", "The programme",
                                                                                       "Your previous", "Make these",
                                                                                       "These are not", "- "))]
        text = _PLANTED.sub("", " ".join(body)).strip()
        if "remove them" not in prompt:
            text += " " + " ".join(f"I also have the {t}." for t in _TRAPS.get("current", []))
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"text": text})])

    return FunctionModel(answer)


_TRAPS: dict[str, list[str]] = {}
_PLANTED = __import__("re").compile(r" ?I also have the [^.]*\.")


def draft_one(writer, critic, wspec, cspec, inputs: Inputs) -> dict:
    """The os.statement loop (run.py) without the database: write, check, review, at most 2 revisions."""
    src = sources(inputs)
    spent = []
    r = write(writer, wspec, inputs)
    spent.append((r.usage, wspec.tier))
    if r.output is None:
        return {"text": None, "flags": [], "usage": spent, "error": (r.error or "").split(":", 1)[0]}
    text = r.output.text
    flags = [c.text for c in unsupported(text, src)]
    for revision in range(MAX_REVISIONS + 1):
        rev = review(critic, cspec, inputs, text, flags)
        spent.append((rev.usage, cspec.tier))
        if rev.output is None or (rev.output.ok and not flags) or revision == MAX_REVISIONS:
            break
        redo = write(writer, wspec, inputs, text, rev.output.fixes, flags)
        spent.append((redo.usage, wspec.tier))
        if redo.output is None:
            break
        text = redo.output.text
        flags = [c.text for c in unsupported(text, src)]
    return {"text": text, "flags": flags, "usage": spent, "error": None}


def _contains(text: str, phrase: str) -> bool:
    return phrase.casefold() in text.casefold()


def _flagged(phrase: str, flags: list[str]) -> bool:
    p = phrase.casefold()
    return any(f.casefold() in p or p in f.casefold() for f in flags)


def check_fictional(personas: list[dict], drafts: dict) -> dict:
    """Counts only. drafts: {(persona_id, kind): {"text", "flags"}}."""
    planted_present = planted_flagged = over_limit = leaks = failed = 0
    for p in personas:
        others = [d for o in personas if o["id"] != p["id"] for d in o["traps"].get("distinctive", [])]
        for kind in KINDS:
            d = drafts[(p["id"], kind)]
            if d["text"] is None:
                failed += 1
                continue
            for trap in p["traps"].get("invented", []):
                if _contains(d["text"], trap):
                    planted_present += 1
                    planted_flagged += _flagged(trap, d["flags"])
            if d["over_by"] > 0 and not d["labelled"]:
                over_limit += 1
            leaks += sum(_contains(d["text"], o) for o in others)
    return {"drafts": 2 * len(personas), "failed": failed, "planted_in_drafts": planted_present,
            "planted_flagged": planted_flagged, "unlabelled_over_limit": over_limit, "cross_persona_leaks": leaks,
            "passed": failed == 0 and planted_flagged == planted_present and over_limit == 0 and leaks == 0}


def run_once(data: dict, cfg, writer, critic, wspec, cspec, settings, billed: bool, out_dir: Path | None) -> dict:
    started, drafts, spent = time.monotonic(), {}, 0.0
    for p in data["personas"]:
        _TRAPS["current"] = p["traps"].get("invented", []) if "traps" in p else []
        for kind in KINDS:
            inputs = inputs_of(p, cfg, kind)
            d = draft_one(writer, critic, wspec, cspec, inputs)
            words = len((d["text"] or "").split())
            limit = inputs.rules.limit_words
            d["over_by"] = max(0, words - limit) if limit else 0
            d["labelled"] = True  # the editor always shows "Over by N words" next to the count (spec §5)
            drafts[(p["id"], kind)] = d
            if billed:
                spent += sum(cost(u, settings, tier) for u, tier in d["usage"])
            if out_dir is not None and d["text"] is not None:
                out_dir.mkdir(parents=True, exist_ok=True)
                (out_dir / f"{p['id']}-{kind}.txt").write_text(d["text"], encoding="utf-8")
    result = {"personas": len(data["personas"]), "cost_usd": round(spent, 4),
              "elapsed_s": round(time.monotonic() - started, 1),
              "flags_per_draft": round(sum(len(d["flags"]) for d in drafts.values()) / max(1, len(drafts)), 2),
              "over_limit_drafts": sum(d["over_by"] > 0 for d in drafts.values())}
    if all("traps" in p for p in data["personas"]):
        result |= check_fictional(data["personas"], drafts)
    return result


def score_ratings(directory: Path, personas: list[dict]) -> dict:
    """The judges' ratings, as counts per kind. Every persona and kind must be rated."""
    ratings = yaml.safe_load((directory / "ratings.yaml").read_text(encoding="utf-8")) or {}
    out, passed = {}, True
    for kind in KINDS:
        rated = [ratings.get(p["id"], {}).get(kind) for p in personas]
        if any(r is None for r in rated):
            raise ValueError(f"ratings.yaml: not every persona has a {kind} rating")
        usable = sum(bool(r["usable_after_one_edit"]) for r in rated)
        invented = sum(int(r["invented_facts"]) for r in rated)
        out[kind] = {"rated": len(rated), "usable_after_one_edit": usable, "invented_facts": invented}
        passed &= usable >= GATE_USABLE * len(rated) / 10 and invented == 0
    out["passed"] = passed
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", choices=["openai", "test"], default="test")
    ap.add_argument("--set", choices=["fictional", "roleplay"], required=True, dest="which")
    ap.add_argument("--dir", type=Path, help="the set's folder (default: by --set)")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--score", action="store_true", help="read the judges' ratings.yaml back instead of drafting")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)

    directory = args.dir or (FICTIONAL if args.which == "fictional" else ROLEPLAY)
    if not (directory / "personas.yaml").is_file():
        print(f"the {args.which} set is not here: {directory}", file=sys.stderr)
        return 2
    data = load_set(directory)
    if args.score:
        result = score_ratings(directory, data["personas"])
        print(" ".join(f"{k}: usable {v['usable_after_one_edit']}/{v['rated']}, invented {v['invented_facts']};"
                       for k, v in result.items() if k != "passed") + f" -> {'PASS' if result['passed'] else 'FAIL'}")
        args.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0 if result["passed"] else 1
    import os

    passed_env = {k: v for k, v in os.environ.items() if k == "OS_OPENAI_API_KEY" or k.startswith(("OS_PRICE_", "OS_MODEL_"))}
    settings = load_settings({"OS_DATABASE_URL": "postgresql://unused/x", **passed_env})
    wspec, cspec = load_agent_spec(AGENT_DIR / "writer.v1.yaml"), load_agent_spec(AGENT_DIR / "critic.v1.yaml")
    if args.model == "openai":
        if not settings.openai_api_key:
            print("OS_OPENAI_API_KEY is not set", file=sys.stderr)
            return 2
        if None in (settings.price_strong_in, settings.price_strong_cached, settings.price_strong_out):
            print("the strong tier's list prices are not set (OS_PRICE_STRONG_IN/_CACHED/_OUT)", file=sys.stderr)
            return 2
    cfg = load_statement_configs()[data["route"]]
    model = model_for(settings, wspec.tier) if args.model == "openai" else _test_model()
    writer, critic = build_agents(model, wspec, cspec)
    runs = []
    for i in range(1, args.runs + 1):
        out_dir = directory / "drafts" if args.which == "roleplay" else None
        r = run_once(data, cfg, writer, critic, wspec, cspec, settings, args.model == "openai", out_dir)
        runs.append(r)
        line = (f"run {i}: {r['personas']} personas, flags per draft {r['flags_per_draft']}, "
                f"over the limit {r['over_limit_drafts']}, cost ${r['cost_usd']:.2f}, {r['elapsed_s']}s")
        if "passed" in r:
            line += (f"; planted {r['planted_flagged']}/{r['planted_in_drafts']} flagged, leaks "
                     f"{r['cross_persona_leaks']}, failed {r['failed']} -> {'PASS' if r['passed'] else 'FAIL'}")
        print(line)
    args.out.write_text(json.dumps({"set": args.which, "model": args.model, "runs": runs}, indent=2), encoding="utf-8")
    return 0 if all(r.get("passed", True) for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
