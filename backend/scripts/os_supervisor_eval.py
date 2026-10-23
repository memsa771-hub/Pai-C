"""The Supervisor evaluation (Slice 7 spec §8). BILLED: it calls the strong model once per case (about 20 calls).
It runs only with the owners' OK, given as `--i-have-the-owners-ok`. Fictional cases only; no database.

    python scripts/os_supervisor_eval.py --i-have-the-owners-ok [--cases tests/os/supervisor_eval.yaml]

A case passes when the operations include every `required` op, none of the `forbidden` ones, and the kernel's
static checks refuse none of them. Prints a JSON report with the score and the cost. Never prints the key.
"""

import argparse
import json
import sys
from pathlib import Path

import yaml

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
DEFAULT_CASES = BACKEND / "tests" / "os" / "supervisor_eval.yaml"
PASS_MARK = 18


def case_state(case: dict):
    from app.os.replan.events import Event
    from app.os.replan.ops import TaskRow
    from app.os.replan.rules import PlanState

    tasks = {}
    for key, state, kind, critical, slack, deps in case["tasks"]:
        ref = key.split("@", 1)[1] if "@" in key else None
        tasks[key] = TaskRow(key, key.split("@")[0], ref, state, kind, bool(critical), key == "visa_apply", None,
                             int(slack), 2, tuple((d, True) for d in deps.split(",") if d))
    programmes = case.get("programmes") or ["p1"]
    state = PlanState(1, "germany_master", programmes, tasks, case.get("suggestions") or {})
    events = [Event(i, 1, None, e["type"], {k: v for k, v in e.items() if k != "type"})
              for i, e in enumerate(case["events"], 1)]
    return state, events


def grade(case: dict, ops, state, book) -> tuple[bool, list[str]]:
    from app.os.replan.checks import _loses_input, _static

    names = [o.op for o in ops]
    why = [f"missing {r}" for r in case["expect"]["required"] if r not in names]
    why += [f"forbidden {f}" for f in case["expect"]["forbidden"] if f in names]
    for op in ops:
        refused = _static(op, state.tasks, book, lambda ref: ref in sum(state.suggestions.values(), [])) \
            or _loses_input([op], state.tasks)
        if refused:
            why.append(f"kernel refuses {op.op}: {refused}")
    return not why, why


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--i-have-the-owners-ok", dest="ok", action="store_true",
                    help="confirm the owners approved this billed run")
    ap.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    args = ap.parse_args(argv)
    if not args.ok:
        print("Refusing: this run is billed. Re-run with --i-have-the-owners-ok once the owners approve.",
              file=sys.stderr)
        return 2

    from app.os.agents.spec import AGENT_DIR, load_agent_spec
    from app.os.knowledge.research.readings import cost, model_for
    from app.os.playbooks import load_playbook_dir
    from app.os.replan.supervisor import build_supervisor, propose
    from app.os.settings import load_settings

    import os

    settings = load_settings(dict(os.environ))
    if not settings.openai_api_key:
        print("OS_OPENAI_API_KEY is not set.", file=sys.stderr)
        return 2
    spec = load_agent_spec(AGENT_DIR / "supervisor.v1.yaml")
    agent = build_supervisor(model_for(settings, spec.tier), spec)
    book = next(b for (k, _), b in load_playbook_dir().items() if k == "germany_master")
    cases = yaml.safe_load(args.cases.read_text(encoding="utf-8"))
    report, passed, spent = [], 0, 0.0
    for case in cases:
        state, events = case_state(case)
        result = propose(agent, spec, state, events, case.get("refused", []), book)
        spent += cost(result.usage, settings, spec.tier)
        if result.output is None:
            report.append({"id": case["id"], "pass": False, "why": [f"no valid output: {result.error}"]})
            continue
        ok, why = grade(case, result.output.ops, state, book)
        passed += ok
        report.append({"id": case["id"], "pass": ok, "why": why, "ops": [o.model_dump() for o in result.output.ops]})
    print(json.dumps({"passed": passed, "of": len(cases), "pass_mark": PASS_MARK, "cost_usd": round(spent, 4),
                      "cases": report}, indent=1))
    return 0 if passed >= PASS_MARK else 1


if __name__ == "__main__":
    raise SystemExit(main())
