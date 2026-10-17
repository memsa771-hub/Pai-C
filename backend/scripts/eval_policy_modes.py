"""Offline, deterministic comparison of the guided and strict counseling policies.

Replays scripted persona turns (recorded classifier signals and coverage) through
the real derive_state and decide functions in both modes. No model, network or
database is used. Reply quality needs real replies: run the printed live command
for that, only after approval.

Simulated reply rule (upper bound): when a question is allowed the reply is
assumed to ask one; otherwise it is a statement. The guided Voice is told that
often the best reply has no question, so real guided question counts can only be
lower than reported here.
"""
import argparse
import json
from pathlib import Path

from app.pai_c.policy import controller
from app.pai_c.policy.classifier import Signals, fallback_signals
from app.pai_c.policy.state import decision_log, derive_state

ROOT = Path(__file__).resolve().parent
FIXTURES = ROOT.parent / "tests" / "fixtures" / "policy_personas"
RESULTS = ROOT / "results"
MODES = ("guided", "strict")
SERVES_REQUEST = {"answer_request", "counsel", "guide"}
LIVE_COMMAND = ("python -m scripts.eval_counselor_deep --live --max-cost-usd 3 --policy-mode {mode} "
                "--max-turns 12 {personas} --result-dir scripts/results/policy_{mode}")


def load_scripts(directory: Path = FIXTURES) -> list[dict]:
    scripts = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(directory.glob("*.json"))]
    if not scripts or len({item["id"] for item in scripts}) != len(scripts):
        raise ValueError("policy persona fixtures must exist and have unique ids")
    return scripts


def _signals(turn: dict) -> Signals:
    data = fallback_signals().model_dump()
    data.update({key: turn[key] for key in ("intent", "emotion", "request", "safety",
                                            "mentioned_areas", "declined_area") if key in turn})
    return Signals.model_validate(data)


def replay(script: dict, mode: str) -> list[dict]:
    areas = controller.load_data("areas_policy.json")["priority"]
    prior, replies, ordinals, rows = [], [], {}, []
    for index, turn in enumerate(script["turns"], start=1):
        event_id = f"{script['id']}-{index}"
        ordinals[event_id] = index
        signals = _signals(turn)
        state = derive_state(signals, coverage={area: {"covered": area in turn.get("covered", [])} for area in areas},
                             mirror_ready=False, plan=None, student_count=index, prior_decisions=prior,
                             replies=replies, student_ordinals=dict(ordinals), current_event_id=event_id)
        state.update(mirror_correction=False, mirror_allowed=False, discover_available=False,
                     possibility_id=None, open_requests=[])
        decision = controller.decide(state, mode=mode)
        asks = decision.question_allowed and decision.action != "care"
        replies.append("A reply that asks one thing?" if asks else "A reply that gives something.")
        prior.append({"event_id": event_id, "decision": decision_log(decision, signals)})
        rows.append({"turn": index, "student": turn["student"], "rule_id": decision.rule_id,
                     "action": decision.action, "question_allowed": decision.question_allowed,
                     "request": signals.request is not None, "safety": signals.safety.level,
                     "intent": signals.intent})
    return rows


def metrics(rows: list[dict]) -> dict:
    streak = longest = 0
    for row in rows:
        streak = streak + 1 if row["question_allowed"] else 0
        longest = max(longest, streak)
    requests = [row for row in rows if row["request"] and row["safety"] == "none"]
    unsafe = [row for row in rows if row["safety"] != "none"]
    return {
        "turns": len(rows),
        "question_turns_max": sum(row["question_allowed"] for row in rows),
        "statement_turns": sum(not row["question_allowed"] for row in rows),
        "longest_question_streak": longest,
        "requests_served": f"{sum(row['action'] in SERVES_REQUEST for row in requests)}/{len(requests)}",
        "guide_before_picture": sum(row["action"] == "guide" for row in rows),
        "first_picture_turn": next((row["turn"] for row in rows if row["action"] == "first_picture"), None),
        "safety_to_care": f"{sum(row['action'] == 'care' for row in unsafe)}/{len(unsafe)}",
        "actions": sorted({row["action"] for row in rows}),
    }


def run(directory: Path = FIXTURES) -> dict:
    report = {"personas": []}
    for script in load_scripts(directory):
        entry = {"id": script["id"], "kind": script["kind"], "modes": {}}
        for mode in MODES:
            rows = replay(script, mode)
            entry["modes"][mode] = {"metrics": metrics(rows), "turns": rows}
        report["personas"].append(entry)
    ids = " ".join(f"--persona {item['id']}" for item in report["personas"])
    report["live_commands"] = [LIVE_COMMAND.format(mode=mode, personas=ids) for mode in MODES]
    return report


def markdown(report: dict) -> str:
    keys = ("question_turns_max", "longest_question_streak", "requests_served",
            "guide_before_picture", "first_picture_turn", "safety_to_care")
    lines = ["# Guided vs strict policy (offline replay)", "",
             "| persona | mode | " + " | ".join(keys) + " |", "|" + "---|" * (len(keys) + 2)]
    for entry in report["personas"]:
        for mode in MODES:
            values = entry["modes"][mode]["metrics"]
            lines.append(f"| {entry['id']} | {mode} | " + " | ".join(str(values[key]) for key in keys) + " |")
    lines += ["", "question_turns_max is an upper bound: it assumes every allowed question is asked.",
              "guide_before_picture counts guide decisions; guided mode allows guide only after confirmation.",
              "", "Live comparison (needs approval, capped at $3 per mode):", ""]
    lines += [f"    {command}" for command in report["live_commands"]]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result-dir", type=Path, default=RESULTS)
    args = parser.parse_args()
    report = run()
    args.result_dir.mkdir(parents=True, exist_ok=True)
    (args.result_dir / "policy_modes.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                                                       encoding="utf-8")
    text = markdown(report)
    (args.result_dir / "policy_modes.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
