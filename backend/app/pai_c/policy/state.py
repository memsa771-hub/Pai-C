"""Workspace-scoped causal inputs and deterministic controller signals."""
from sqlalchemy import select

from app.config import config
from app.models import CounselorTurnDecision, EventRecord, BackgroundJob, StudentJourney, StudentJourneyEvent, PaiPossibility
from datetime import timezone
from app.pai_c.memory import MemoryService
from app.pai_c.policy.controller import load_data
from app.pai_c.voice.guards import question_sentences


def first_picture_due(*, coverage, student_count, prior_decisions, summary_confirmed):
    """Once per workspace, before confirmation, after enough messages and coverage,
    and only when the required areas (where they are now and their story so far) are covered."""
    rules = load_data("guided_table.json")["derived"]
    covered = sum(bool(area.get("covered")) for area in coverage.values())
    return (not summary_confirmed
            and not any(row["decision"].get("action") == rules["first_picture_action"] for row in prior_decisions)
            and student_count >= rules["first_picture_min_student_messages"]
            and covered >= rules["first_picture_min_covered_areas"]
            and all(coverage.get(area, {}).get("covered") for area in rules["first_picture_required_areas"]))


def derive_state(signals, *, coverage, mirror_ready, plan, student_count,
                 prior_decisions, replies, student_ordinals, current_event_id,
                 summary_confirmed=False):
    policy = load_data("decision_table.json")["derived"]
    data = signals.model_dump()
    previous = prior_decisions[-1]["decision"] if prior_decisions else {}
    covered = sum(bool(area.get("covered")) for area in coverage.values())
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
    return {**data, "coverage": coverage, "mirror_ready": mirror_ready,
            "student_count": student_count, "previous": previous,
            "previous_mentioned_areas": previous.get("signals", {}).get("mentioned_areas", []),
            "declined_at": declines, "short_reply_streak": streak,
            "questions_in_last_two": len(replies) >= window and all(
                any(question_sentences(reply)) for reply in replies[-window:]),
            "summary_due": student_count - max(summaries, default=0) >= config.PAI_SUMMARY_EVERY_TURNS
                and covered >= policy["summary_min_covered"],
            "insight_available": bool(plan and plan.give.strip()),
            "summary_confirmed": summary_confirmed,
            "first_picture_due": first_picture_due(coverage=coverage, student_count=student_count,
                prior_decisions=prior_decisions, summary_confirmed=summary_confirmed),
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
    state = derive_state(signals, coverage=memory.coverage_areas(turn.workspace_id),
        mirror_ready=memory.truth_map(turn.workspace_id).notebook.mirror_ready,
        plan=plan, student_count=len(ordinals), prior_decisions=prior,
        replies=[row["content"] for row in history if row["role"] == "assistant"],
        student_ordinals=ordinals, current_event_id=turn.source_event_id)
    from app.pai_c.deep.noted_questions import NotedQuestionService
    state["open_requests"] = NotedQuestionService(db).open_requests(turn.workspace_id)
    current = db.scalar(select(EventRecord).where(
        EventRecord.network_id == turn.workspace_id, EventRecord.id == turn.source_event_id))
    edits = db.scalars(select(EventRecord).where(
        EventRecord.network_id == turn.workspace_id, EventRecord.id.in_(list(ordinals)),
        EventRecord.metadata_["mirror_edit_version"].as_string().is_not(None),
    ).order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())).all()
    last_edit = edits[0] if edits else None
    journey = db.scalar(select(StudentJourney).where(
        StudentJourney.workspace_id == turn.workspace_id,
        StudentJourney.journey_type == "counselor_decision", StudentJourney.status == "active"))
    pending = db.scalar(select(BackgroundJob.id).where(
        BackgroundJob.workspace_id == turn.workspace_id, BackgroundJob.job_type == "counselor.mirror",
        BackgroundJob.status.in_(("pending", "running"))).limit(1))
    enough_after_edit = last_edit is None or (
        len(ordinals) - ordinals[last_edit.id] >= load_data("decision_table.json")["derived"]["mirror_after_edit_min_student_messages"]
        and memory.patch_applied_since(turn.workspace_id, last_edit.id))
    state["mirror_correction"] = bool(current and (current.metadata_ or {}).get("mirror_edit_version") is not None)
    state["mirror_allowed"] = bool(state["mirror_ready"] and journey
        and journey.current_stage == "DIRECTION" and pending is None and enough_after_edit)
    state["discover_available"] = False
    state["possibility_id"] = None
    draft = (journey.counselor_summary_draft or {}) if journey else {}
    state["summary_confirmed"] = draft.get("status") == "confirmed"
    if state["summary_confirmed"]:
        state["first_picture_due"] = False
        proof = db.scalar(select(StudentJourneyEvent).where(
            StudentJourneyEvent.workspace_id == turn.workspace_id,
            StudentJourneyEvent.event_type == "counselor.mirror.confirmed",
            StudentJourneyEvent.payload["mirror_version"].as_integer() == draft.get("version")
        ).order_by(StudentJourneyEvent.created_at.desc()).limit(1))
        possibility = db.scalar(select(PaiPossibility).where(
            PaiPossibility.workspace_id == turn.workspace_id, PaiPossibility.status == "suggested",
            PaiPossibility.mentioned_at.is_(None)).order_by(PaiPossibility.created_at, PaiPossibility.id).limit(1))
        if proof and possibility:
            confirmed = proof.created_at.replace(tzinfo=timezone.utc) if proof.created_at.tzinfo is None else proof.created_at
            boundary = max([int(confirmed.timestamp() * 1000), *[
                row.source_timestamp for row in rows if (row.decision or {}).get("action") == "discover"]])
            count = sum(row["timestamp"] > boundary for row in students)
            state["discover_available"] = count >= load_data("decision_table.json")["derived"]["discover_min_student_messages_between"]
            state["possibility_id"] = possibility.id
    return state


def decision_log(decision, signals):
    request = signals.request
    return {**decision.as_dict(), "signals": {
        "intent": signals.intent, "emotion": signals.emotion,
        "request_kind": request.kind if request else None,
        "needs_research": request.needs_research if request else None,
        "needs_context": request.needs_context if request else None,
        "mentioned_areas": signals.mentioned_areas, "declined_area": signals.declined_area}}
