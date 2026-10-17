"""Generic first-match and post-check evaluator; counseling rules live in JSON."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

POLICY_DIR = Path(__file__).parent


def load_data(name):
    return json.loads((POLICY_DIR / name).read_text(encoding="utf-8"))


def at_path(state, path):
    for part in path.split("."):
        state = state.get(part) if isinstance(state, dict) else None
    return state


def evaluate(expression, state):
    if not isinstance(expression, dict):
        return expression
    operation, value = next(iter(expression.items()))
    if operation == "ref":
        return at_path(state, value)
    if operation == "if":
        return evaluate(value[1] if evaluate(value[0], state) else value[2], state)
    if operation == "all":
        return all(evaluate(item, state) for item in value)
    if operation == "first":
        return next(iter(evaluate(value, state) or []), None)
    left, right = (evaluate(item, state) for item in value)
    if operation == "eq":
        return left == right
    if operation == "ne":
        return left != right
    if operation == "in":
        return left in right
    if operation == "gte":
        return left >= right
    raise ValueError("Unknown decision expression operator")


@dataclass(frozen=True)
class Decision:
    rule_id: str
    action: str
    topic: str | None
    question_allowed: bool
    invite: bool
    summary_due: bool

    def as_dict(self):
        return asdict(self)


def askable_areas(state, policy=None, excluded=()):
    policy = policy if policy is not None else load_data("areas_policy.json")
    count = state["student_count"]
    mentioned = state.get("mentioned_areas", [])
    previous = state.get("previous_mentioned_areas", [])
    candidates = []
    for area in policy["priority"]:
        if area in excluded or state.get("coverage", {}).get(area, {}).get("covered", False):
            continue
        declined_at = state.get("declined_at", {}).get(area)
        if declined_at is not None and count - declined_at < policy["declined_cooldown_student_messages"]:
            continue
        rule = policy["sensitive"].get(area)
        if rule and count < rule["min_student_messages"]:
            if not (rule["unless_mentioned"] and area in [*mentioned, *previous]):
                continue
        candidates.append(area)
    return sorted(candidates, key=lambda area: (
        0 if area in mentioned else 1 if area in previous else 2,
        policy["priority"].index(area)))


TABLES = {"strict": "decision_table.json", "guided": "guided_table.json"}


def policy_mode(mode=None):
    from app.config import config
    return mode or config.PAI_POLICY_MODE


def decide(state, mode=None):
    table = load_data(TABLES[policy_mode(mode)])
    state = dict(state)
    candidates = askable_areas(state)
    previous = state.get("previous") or {}
    alternatives = askable_areas(state, excluded=(previous.get("topic"),))
    state.update(askable_area=next(iter(candidates), None),
                 next_askable_area=next(iter(alternatives), None), previous=previous)
    row = next(row for row in table["rows"] if evaluate(row["when"], state))
    chosen = {key: evaluate(value, state) for key, value in row["set"].items()}
    rule_id = row["id"]
    for check in table.get("post_checks", []):
        scope = {**state, "chosen": chosen}
        if evaluate(check["when"], scope):
            branch = next((item for item in check["branches"] if evaluate(item["when"], scope)), None)
            if branch:
                replacement = {key: evaluate(value, scope) for key, value in branch["set"].items()}
                if replacement != chosen:
                    chosen = replacement
                    rule_id += "+" + check["id"]
    return Decision(rule_id=rule_id, summary_due=state["summary_due"], **chosen)


def decision_context(decision, signals, plan, possibility=None):
    areas = load_data("areas_policy.json")
    request = signals.request if signals is not None else None
    topic_text = request.text if decision.topic == "request" and request else areas["topic_text"].get(decision.topic, "")
    instruction = (POLICY_DIR / "actions" / (decision.action + ".md")).read_text(encoding="utf-8")
    instruction = instruction.replace("{topic_text}", topic_text)
    instruction = instruction.replace("{topic_clause}", " (about " + topic_text + ")" if topic_text else "")
    if possibility is not None:
        instruction = instruction.replace("{possibility_title}", possibility.title).replace("{possibility_why}", possibility.why)
    if decision.invite:
        instruction += "\n" + (POLICY_DIR / "actions/invite.md").read_text(encoding="utf-8")
    return {"action": decision.action, "topic_text": topic_text,
            "question_allowed": decision.question_allowed, "instruction": instruction,
            "avoid_questions": plan.avoid_questions if plan else [],
            "insight_candidate": plan.give if plan else ""}
