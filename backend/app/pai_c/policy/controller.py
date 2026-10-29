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
    if operation == "any":
        return any(evaluate(item, state) for item in value)
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
    # The drive rule: the reply must end with `next_step` (a question or a
    # concrete action). Set by `decide`; a hand-built decision does not drive.
    must_drive: bool = False
    next_step: dict | None = None
    # The question-bank ledger: the bank item this reply asks, and whether it
    # is that item's one follow-up.
    bank_intent: str | None = None
    bank_followup: bool = False

    def as_dict(self):
        return asdict(self)


def askable_areas(state, policy=None, excluded=()):
    """The Vault's unknown areas (pai_c/completeness.py, priority order) that
    pass the cooldown and sensitivity rules; one list with the completeness meter."""
    from app.pai_c.completeness import unknown_areas
    policy = policy if policy is not None else load_data("areas_policy.json")
    count = state["student_count"]
    mentioned = state.get("mentioned_areas", [])
    previous = state.get("previous_mentioned_areas", [])
    candidates = []
    for area in unknown_areas(state.get("coverage", {}), policy):
        if area in excluded or area not in policy["priority"]:
            continue
        declined_at = state.get("declined_at", {}).get(area)
        if declined_at is not None and count - declined_at < policy["declined_cooldown_student_messages"]:
            continue
        # Values and strengths are not education basics; PAI follows them only once the student raises them.
        if area in policy.get("only_if_mentioned", []) and area not in [*mentioned, *previous]:
            continue
        rule = policy["sensitive"].get(area)
        if rule and count < rule["min_student_messages"]:
            if not (rule["unless_mentioned"] and area in [*mentioned, *previous]):
                continue
        candidates.append(area)
    return sorted(candidates, key=lambda area: (
        0 if area in mentioned else 1 if area in previous else 2,
        policy["priority"].index(area)))


def bank_item(intent_key):
    return next((item for item in load_data("question_bank.json")["items"]
                 if item["intent_key"] == intent_key), None)


def next_step(state, chosen):
    """What this reply ends with (next_steps.json). In a phase that asks, a
    reply allowed a question (or one answering a request) ends with the bank
    question (this move's, else the next one), else the next missing education
    basic; otherwise with the phase's line, a concrete action that names a
    workspace place (in the chosen phase, the route's first open step).
    `question` says whether the step is a question; `line` is the phase line,
    the fallback when a question step would repeat one already asked."""
    data = load_data("next_steps.json")
    phase = data["stage_phase"].get(state.get("journey_stage") or "", data["default_phase"])
    rules = data["phases"][phase]
    step = {"phase": phase, "place": None, "question": True, "line": rules["line"], "line_place": rules["place"]}
    if rules["ask"] and (chosen.get("question_allowed") or chosen.get("action") in data["question_after_actions"]):
        item = bank_item(chosen.get("bank_intent")) or state.get("next_bank_item")
        if item:
            followup = chosen.get("bank_followup") if chosen.get("bank_intent") else item.get("followup")
            return {**step, "key": "bank:" + item["intent_key"] + (":followup" if followup else ""),
                    "text": item["followup_prompt"] if followup else item["prompt"]}
        basic = state.get("askable_basic") or state.get("askable_area")
        if basic:
            topic_text = load_data("areas_policy.json")["topic_text"].get(basic, "")
            return {**step, "key": "basic:" + basic, "text": data["basic_question"].format(topic_text=topic_text)}
    text = rules["line"]
    if rules.get("step_line") and state.get("route_step"):
        text = rules["step_line"].format(step=state["route_step"])
    return {**step, "question": False, "key": "phase:" + phase, "text": text, "place": rules["place"]}


def decide(state):
    table = load_data("guided_table.json")
    state = {"question_needed": False, **state}
    candidates = askable_areas(state)
    previous = state.get("previous") or {}
    alternatives = askable_areas(state, excluded=(previous.get("topic"),))
    basics = load_data("areas_policy.json").get("education_basics", [])
    state.update(askable_area=next(iter(candidates), None),
                 next_askable_area=next(iter(alternatives), None), previous=previous,
                 askable_basic=next((area for area in candidates if area in basics), None))
    # After bank_max_in_a_row bank questions, a missing education basic comes
    # first; the bank continues after it (question_bank.json).
    bank = load_data("question_bank.json")
    state["basic_due"] = bool(state.get("next_bank_item") and state["askable_basic"]
                              and state.get("bank_streak", 0) >= bank["bank_max_in_a_row"])
    if state["basic_due"]:
        state["next_bank_item"] = None
    # The classifier judges one message; a missing education basic is a reason to ask that it cannot see.
    state["question_due"] = evaluate(table.get("question_due", {"ref": "question_needed"}), state)
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
    drive = table.get("drive", {})
    must_drive = (chosen["action"] not in drive.get("exempt_actions", ())
                  and state.get("intent") not in drive.get("exempt_intents", ()))
    return Decision(rule_id=rule_id, summary_due=state["summary_due"], must_drive=must_drive,
                    next_step=next_step(state, chosen) if must_drive else None, **chosen)


def decision_context(decision, signals, plan, possibility=None):
    areas = load_data("areas_policy.json")
    request = signals.request if signals is not None else None
    topic_text = request.text if decision.topic == "request" and request else areas["topic_text"].get(decision.topic, "")
    instruction = (POLICY_DIR / "actions" / (decision.action + ".md")).read_text(encoding="utf-8")
    instruction = instruction.replace("{topic_text}", topic_text)
    instruction = instruction.replace("{topic_clause}", " (about " + topic_text + ")" if topic_text else "")
    item = bank_item(decision.bank_intent)
    if item:
        instruction = instruction.replace("{bank_prompt}", item["followup_prompt"] if decision.bank_followup else item["prompt"])
    if possibility is not None:
        instruction = instruction.replace("{possibility_title}", possibility.title).replace("{possibility_why}", possibility.why)
    if decision.invite:
        instruction += "\n" + (POLICY_DIR / "actions/invite.md").read_text(encoding="utf-8")
    return {"action": decision.action, "topic_text": topic_text,
            "question_allowed": decision.question_allowed, "instruction": instruction,
            "student_emotion": signals.emotion if signals is not None else None,
            "next_step": decision.next_step["text"] if decision.must_drive and decision.next_step else None,
            "avoid_questions": plan.avoid_questions if plan else [],
            "insight_candidate": plan.give if plan else ""}
