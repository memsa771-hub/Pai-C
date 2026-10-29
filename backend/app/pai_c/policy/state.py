"""Workspace-scoped causal inputs and deterministic controller signals."""
from sqlalchemy import select

from app.config import config
from app.models import CounselorTurnDecision, StudentJourney, PaiPossibility
from app.pai_c.memory import MemoryService
from app.pai_c.policy.controller import load_data
from app.pai_c.voice.guards import question_sentences


def _known(area: dict) -> bool:
    """Known as the Vault completeness meter counts it: covered and not stale."""
    return bool(area.get("covered")) and not area.get("stale")


def first_picture_due(*, coverage, student_count, prior_decisions, mirror_ready):
    """A provisional picture uses evidence coverage, never elapsed turn count.
    Once the Mirror is ready the card is the picture."""
    rules = load_data("guided_table.json")["derived"]
    known = sum(_known(area) for area in coverage.values())
    return (not mirror_ready
            and not any(row["decision"].get("action") == rules["first_picture_action"] for row in prior_decisions)
            and known >= rules["first_picture_min_covered_areas"]
            and all(_known(coverage.get(area, {})) for area in rules["first_picture_required_areas"]))


def bank_asked(prior_decisions, asking) -> list[str]:
    """Bank intents already asked (the ledger in the turn decisions). Once any
    PAI reply has asked a question the conversation is past its open first
    question (the opening or the intro), so that item counts as asked."""
    bank = load_data("question_bank.json")
    asked = [intent for row in prior_decisions
             for intent in (row["decision"].get("bank_intent"), row["decision"].get("step_bank_intent")) if intent]
    if any(asking):
        asked.append(bank["first_item"])
    return list(dict.fromkeys(asked))


def next_bank_item(*, vault_types, asked, previous, intent, mentioned, declined_at, student_count):
    """The bank question for this reply (BETA_CONVERSATION_SPEC 2.2/2.3), or None.
    A short answer to the previous bank question gets its follow-up once;
    otherwise the first item not asked whose Vault types are still empty,
    whose area the student did not just cover, and which passes the area's
    decline cooldown and sensitivity rules."""
    bank = load_data("question_bank.json")
    if intent in bank["skip_intents"]:
        return None
    items = {item["intent_key"]: item for item in bank["items"]}
    areas = load_data("areas_policy.json")
    previous_item = items.get(previous.get("bank_intent"))
    if (previous_item and intent == load_data("guided_table.json")["derived"]["short_reply_intent"]
            and not previous.get("bank_followup") and not set(previous_item["vault_types"]) & vault_types):
        return {**previous_item, "followup": True}
    for item in bank["items"]:
        area = item["area"]
        if item["intent_key"] in asked or set(item["vault_types"]) & vault_types or area in mentioned:
            continue
        declined = declined_at.get(area)
        if declined is not None and student_count - declined < areas["declined_cooldown_student_messages"]:
            continue
        rule = areas["sensitive"].get(area)
        if rule and student_count < rule["min_student_messages"]:
            continue
        return {**item, "followup": False}
    return None


def route_next_step(db, workspace_id: str) -> str | None:
    """The active route decision's first step that is not done (its choose-time
    snapshot and the student's ticks), in its roadmap.json copy; None without one."""
    from app.pai_c.roadmap.decisions import RouteDecisionService, done_keys
    row = RouteDecisionService(db).active(workspace_id)
    if row is None:
        return None
    done, copy = set(done_keys(row)), load_data("roadmap.json")["copy"]
    for step in row.steps or []:
        template = copy.get(step.get("label_key"))
        if step.get("status") == "done" or step.get("key") in done or not template:
            continue
        values = {key: ", ".join(map(str, value)) if isinstance(value, list) else value
                  for key, value in (step.get("values") or {}).items()}
        try:
            return template.format_map(values)
        except (KeyError, IndexError, ValueError):
            continue
    return None


def derive_state(signals, *, coverage, mirror_ready, plan, student_count,
                 prior_decisions, replies, student_ordinals, current_event_id,
                 reply_requested_input=None, vault_types=None):
    """`vault_types` (the catalog types the Vault holds) turns on the question
    bank; a caller without a Vault read gets no intro or bank move."""
    policy = load_data("guided_table.json")["derived"]
    data = signals.model_dump()
    previous = prior_decisions[-1]["decision"] if prior_decisions else {}
    covered = sum(_known(area) for area in coverage.values())
    by_event = {row["event_id"]: row["decision"] for row in prior_decisions}
    summaries = [student_ordinals.get(row["event_id"], 0) for row in prior_decisions
                 if row["decision"].get("action") == policy["summary_action"]]
    streak = int(data["intent"] == policy["short_reply_intent"])
    if streak:
        for event_id in reversed(list(student_ordinals)):
            if event_id == current_event_id:
                continue
            if by_event.get(event_id, {}).get("signals", {}).get("intent") != policy["short_reply_intent"]:
                break
            streak += 1
    declines = {}
    for row in prior_decisions:
        area = row["decision"].get("signals", {}).get("declined_area")
        if area:
            declines[area] = student_ordinals.get(row["event_id"], 0)
    if data["declined_area"]:
        declines[data["declined_area"]] = student_count
    window = policy["question_window"]
    requested = reply_requested_input or [False] * len(replies)
    asking = [requested[i] or any(question_sentences(reply)) for i, reply in enumerate(replies)]
    bank = {"intro_due": False, "next_bank_item": None, "bank_streak": 0}
    if vault_types is not None:
        asked = bank_asked(prior_decisions, asking)
        skip = load_data("question_bank.json")["skip_intents"]
        streak = 0
        for row in reversed(prior_decisions):
            if not row["decision"].get("bank_intent"):
                break
            streak += 1
        bank = {"bank_streak": streak,
                "intro_due": not any(asking) and data["intent"] not in skip
                    and load_data("question_bank.json")["first_item"] not in asked,
                "next_bank_item": next_bank_item(vault_types=set(vault_types), asked=asked, previous=previous,
                    intent=data["intent"], mentioned=data["mentioned_areas"], declined_at=declines,
                    student_count=student_count)}
    return {**data, **bank, "coverage": coverage, "mirror_ready": mirror_ready,
            "student_count": student_count, "previous": previous,
            "previous_mentioned_areas": previous.get("signals", {}).get("mentioned_areas", []),
            "declined_at": declines, "short_reply_streak": streak,
            "questions_in_last_two": len(asking) >= window and all(asking[-window:]),
            "summary_due": student_count - max(summaries, default=0) >= config.PAI_SUMMARY_EVERY_TURNS
                and covered >= policy["summary_min_covered"],
            "insight_available": bool(plan and plan.give.strip()),
            "first_picture_due": first_picture_due(coverage=coverage, student_count=student_count,
                prior_decisions=prior_decisions, mirror_ready=mirror_ready),
            "invite_pending": covered < policy["invite_max_covered"] and not any(
                row["decision"].get("invite") for row in prior_decisions)}


def build_state(db, turn, signals, history):
    memory = MemoryService(db)
    turns = memory.session_turns(turn.workspace_id)
    students = [row for row in turns if row["role"] == "student" and
                (turn.timestamp is None or row["timestamp"] <= turn.timestamp)]
    ordinals = {row["id"]: index + 1 for index, row in enumerate(students)}
    if turn.source_event_id not in ordinals:
        ordinals[turn.source_event_id] = len(ordinals) + 1
    rows = db.scalars(select(CounselorTurnDecision).where(
        CounselorTurnDecision.workspace_id == turn.workspace_id,
        CounselorTurnDecision.source_event_id.in_(list(ordinals)),
        CounselorTurnDecision.source_event_id != turn.source_event_id,
    ).order_by(CounselorTurnDecision.source_timestamp, CounselorTurnDecision.source_event_id)).all()
    prior = [{"event_id": row.source_event_id, "decision": row.decision or {}} for row in rows]
    plan = memory.latest_plan(turn.workspace_id)
    coverage = memory.coverage_areas(turn.workspace_id)
    from app.pai_c.mirror import ready_from
    # The Mirror state card's `ready`, read once per turn from this coverage.
    mirror_ready = ready_from(coverage)
    vault_types = {row.entry["type"] for row in memory.vault_rows(turn.workspace_id) if not row.entry["stale"]}
    state = derive_state(signals, coverage=coverage, mirror_ready=mirror_ready, vault_types=vault_types,
        plan=plan, student_count=len(ordinals), prior_decisions=prior,
        replies=[row["content"] for row in history if row["role"] == "assistant"],
        reply_requested_input=[bool(row.get("requested_input")) for row in history if row["role"] == "assistant"],
        student_ordinals=ordinals, current_event_id=turn.source_event_id)
    from app.pai_c.deep.noted_questions import NotedQuestionService
    state["open_requests"] = NotedQuestionService(db).open_requests(turn.workspace_id)
    journey = db.scalar(select(StudentJourney).where(
        StudentJourney.workspace_id == turn.workspace_id,
        StudentJourney.journey_type == "counselor_decision", StudentJourney.status == "active"))
    draft = (journey.counselor_summary_draft or {}) if journey else {}
    state["journey_stage"] = journey.current_stage if journey else None
    # The chosen route's first open step names the next step (next_steps.json step_line).
    state["route_step"] = route_next_step(db, turn.workspace_id) if journey and journey.current_stage == "CHOSEN" else None
    # The card is posted in chat once, the first time it is ready (spec 2.5).
    posted = draft.get("mirror_posted_version") if draft.get("type") == "mirror_state" else None
    state["mirror_due"] = bool(mirror_ready and journey is not None and not posted)
    state["discover_available"] = False
    state["possibility_id"] = None
    # Evidence-validated possibilities can be offered tentatively before a Mirror.
    # Being offered one does not select it, authorize execution, or assert eligibility.
    possibility = db.scalar(select(PaiPossibility).where(
        PaiPossibility.workspace_id == turn.workspace_id, PaiPossibility.status == "suggested",
        PaiPossibility.mentioned_at.is_(None)).order_by(PaiPossibility.created_at, PaiPossibility.id).limit(1))
    if possibility and possibility.evidence:
        state["discover_available"] = True
        state["possibility_id"] = possibility.id
    from app.pai_c.myths import relevant_myth
    state["relevant_myth"] = relevant_myth(db, turn.workspace_id, signals)
    return state


def step_bank_intent(decision) -> str | None:
    """The bank item a reply's next step asks ("bank:<intent>[:followup]"),
    e.g. the question an answer ends with, so the ledger never asks it again."""
    key = (decision.next_step or {}).get("key") or ""
    return key.split(":")[1] if key.startswith("bank:") else None


def decision_log(decision, signals):
    request = signals.request
    return {**decision.as_dict(), "step_bank_intent": step_bank_intent(decision), "signals": {
        "intent": signals.intent, "emotion": signals.emotion,
        "request_kind": request.kind if request else None,
        "needs_research": request.needs_research if request else None,
        "needs_context": request.needs_context if request else None,
        "mentioned_areas": signals.mentioned_areas, "declined_area": signals.declined_area,
        "language": signals.language.model_dump() if signals.language else None}}
