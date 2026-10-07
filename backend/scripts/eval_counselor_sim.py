"""Offline research contracts by default; billed conversation simulation with --live.

The live mode needs PAI_API_KEY and may make many billed model calls.
"""

import argparse
import asyncio
import importlib.util
import json
import sys
import traceback
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.config import config
from app.counseling.guard_v2 import deterministic_violations
from app.counseling.turn import CounselorTurnInput, run_counselor_turn
from app.inference.client import chat_completion
from app.memory.student_snapshot import StudentSnapshotService
from app.memory.field_definitions import VaultFieldDefinitionService
from app.models import EventRecord, MemoryCandidate, PaiMemory, ProfileRequirement, StudentJourney, User, Workspace
from scripts.counselor_eval_support import StudentSession


PERSONAS = (
    {"id": "hamza", "opening": "i missed MBBS merit and honestly don't know what to do",
     "facts": "18, Lahore. FSc Pre-Medical 891/1100 completed. Likes biology and lab work, dislikes chemistry. MBBS was father's wish. Lahore or Islamabad only. PKR 3-4 lakh per year. Feeling down.",
     "style": "short lowercase English", "marker": "891/1100"},
    {"id": "ali", "opening": "hey", "facts": "Islamabad. FSc Pre-Engineering 844/1100 completed, highest. Wants bachelor's in USA for good universities and jobs; maybe data science, tech company, perhaps abroad. Budget PKR 15 lakh per year including living. Start next year. No English test.",
     "style": "casual English", "marker": "844/1100"},
    {"id": "ayesha", "opening": "I'm in BS CS semester 6 and looking at what comes next",
     "facts": "BS CS semester 6, CGPA 3.21. Master's abroad, job in Pakistan, or local MS. Earning matters because family needs support. Abroad only if fully funded. Likes web development and some ML. Two-month React internship.",
     "style": "English", "marker": "3.21"},
    {"id": "bilal", "opening": "BS electrical engineering done 2025, CGPA 3.4. IELTS 7.0. I uploaded both. I want MS in Germany in power electronics for EV industry",
     "facts": "Germany for low tuition and EV companies; wants to work there after. Family can pay 10 lakh/year plus savings for blocked account. Winter 2027 intake.",
     "style": "direct English", "marker": "IELTS 7.0"},
    {"id": "sana", "opening": "I work in bank operations and want to move into data analytics",
     "facts": "Karachi, 28, BCom completed 2019. Bank operations since. Likes patterns in Excel reports; wants better pay. Part-time evenings/weekends only. Budget PKR 1 lakh total. Wants to switch within a year.",
     "style": "professional English", "marker": "BCom 2019"},
    {"id": "usman", "opening": "main A Levels year 2 mein hun, aage ka samajh nahi aa raha",
     "facts": "Faisalabad, 17. A-Levels year 2; AS Physics B, Chemistry C, Maths A. Parents want engineering; he likes graphic design and app UI, one year of Figma projects. Father might accept software. Budget 5-6 lakh/year. At turn 6 ask cricket match; at turn 10 ask for physics homework.",
     "style": "Roman Urdu only", "marker": "Faisalabad"},
    {"id": "volunteer", "opening": "I finished a BA in economics last year with a 3.1 GPA, love public policy, want a funded master's abroad to work on education policy, can spend about 2 lakh yearly and start next autumn",
     "facts": "Everything important was volunteered in the first message. Do not repeat these facts unless asked for confirmation.",
     "style": "English", "marker": "education policy"},
    {"id": "contradiction", "opening": "I finished FSc Pre-Engineering with 760 out of 1100",
     "facts": "Later say the marks were 780 out of 1100; this is a correction, not a new FSc. Interested in architecture and urban design; wants local study; budget 4 lakh/year.",
     "style": "English", "marker": "urban design"},
    {"id": "refusal", "opening": "I want to study environmental science but I don't want to share my budget",
     "facts": "Completed FSc Pre-Medical. Interested in conservation work. Refuses to give any budget, should not be pressed again. Wants to start next year near home.",
     "style": "English", "marker": "conservation"},
    {"id": "urdu", "opening": "میں آگے کیا پڑھوں، سمجھ نہیں آ رہا",
     "facts": "Lives in Peshawar. Completed FSc Pre-Medical with 835/1100. Likes laboratory science, wants health research rather than clinical work. Budget about 3 lakh PKR per year; next year.",
     "style": "Urdu script only", "marker": "835/1100"},
)


def _seed_slots(db):
    migration = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "085_counselor_discovery_slots.py"
    spec = importlib.util.spec_from_file_location("counselor_slot_seed", migration)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    definitions = VaultFieldDefinitionService(db)
    definitions.upsert_definition({
        "key": "preferences.location_limits", "category": "preferences",
        "data_type": "array", "validation_schema": {
            "type": "array", "maxItems": 30,
            "items": {"type": "string", "minLength": 1, "maxLength": 200}},
        "cardinality": "single", "conflict_policy": "latest_wins",
        "sensitivity": "normal", "searchable": True,
    })
    definitions.upsert_definition({
        "key": "preferences.study_load", "category": "preferences",
        "data_type": "string", "validation_schema": {
            "type": "string", "enum": ["full_time", "part_time", "flexible"]},
        "cardinality": "single", "conflict_policy": "latest_wins",
        "sensitivity": "normal", "searchable": False,
    })
    for key, stage, priority, source_type, source_key, path, selector, applicability, intent, unknown, en, ur, roman in module.SLOTS:
        if key in {"goal_reason", "field_interest", "envisioned_outcome", "timing"}:
            source_type, source_key, path = "record_field", "student_voice_statement", "statement"
        db.add(ProfileRequirement(
            key=f"discovery.{key}", stage=stage, tier="important",
            source_type=source_type, source_key=source_key, source_path=path,
            selector=selector, applicability=applicability, question=en,
            question_intent=intent, canonical_questions={
                "en": en, "ur": ur, "roman_ur": roman, "mixed": roman},
            accepts_unknown=unknown, priority=priority, version=1,
        ))


async def _student(persona, transcript, turn_number):
    schema = {"type": "object", "properties": {
        "student_message": {"type": "string"},
    }, "required": ["student_message"], "additionalProperties": False}
    prompt = (
        "Play one student in a counseling conversation. The facts below are private to "
        "you. Answer only the Counselor's latest question, naturally and briefly. "
        "Reveal hidden facts only when asked, unless the opening already volunteered "
        "them. Never invent facts or respond as the Counselor. If the Counselor "
        "summarizes accurately, explicitly confirm it; if wrong, correct it. "
        "For a denied budget, politely refuse once and do not disclose it. "
        "Use the specified language and style on EVERY turn; never switch "
        "languages just because the Counselor did. Return JSON only."
    )
    data = {"persona": persona, "turn_number": turn_number,
            "dialogue": transcript[-8:]}
    raw = await chat_completion(
        api_key=config.PAI_API_KEY, model=config.PAI_COUNSELOR_AUX_MODEL or config.PAI_MODEL,
        base_url=config.PAI_BASE_URL, reasoning_effort="minimal", max_tokens=300,
        system_prompt=prompt,
        messages=[{"role": "user", "content": json.dumps(data, ensure_ascii=False)}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "pai_counselor_sim_student", "strict": True, "schema": schema,
        }},
    )
    message = json.loads(raw)["student_message"].strip()
    if not message:
        raise ValueError("Student simulator produced an empty turn")
    return message


async def _judge(persona, transcript):
    schema = {"type": "object", "properties": {
        key: {"type": "boolean"} for key in (
            "natural", "no_verdict", "no_unsourced_facts", "language_match",
            "goal_summary_faithful", "no_unasked_lecture")},
        "required": ["natural", "no_verdict", "no_unsourced_facts",
                     "language_match", "goal_summary_faithful", "no_unasked_lecture"],
        "additionalProperties": False}
    raw = await chat_completion(
        api_key=config.PAI_API_KEY, model=config.PAI_COUNSELOR_AUX_MODEL or config.PAI_MODEL,
        base_url=config.PAI_BASE_URL, reasoning_effort="minimal", max_tokens=250,
        system_prompt=(
            "Judge this one student counseling transcript conservatively. Natural means "
            "brief, relevant, not robotic. No verdict means no doable/impossible/eligible "
            "judgment. No unsourced facts means no fabricated requirements, tests, fees, "
            "deadlines, rankings or statistics. Language match means PAI mirrors the "
            "student's own language. Goal summary faithful means it reflects only stated "
            "student facts and their goal. No unasked lecture means no long advice or "
            "lists not requested. Return booleans only."
        ),
        messages=[{"role": "user", "content": json.dumps({
            "persona": persona, "transcript": transcript,
        }, ensure_ascii=False)}],
        response_format={"type": "json_schema", "json_schema": {
            "name": "pai_counselor_sim_judge", "strict": True, "schema": schema,
        }},
    )
    return json.loads(raw)


def _workspace(session, persona, run):
    with session.factory() as db:
        user = User(email=f"sim-{persona['id']}-{run}-{uuid.uuid4().hex[:8]}@example.test",
                    onboarded_at=datetime.now(timezone.utc))
        db.add(user)
        db.flush()
        workspace = Workspace(name=f"Synthetic {persona['id']} {run}", owner_user_id=user.id,
                              password_hash="synthetic-test-only")
        db.add(workspace)
        db.commit()
        return str(workspace.id), str(user.id)


async def _turn(session, workspace_id, user_id, text, *, target, voice, session_id):
    source_id = str(uuid.uuid4())
    timestamp = session.next_timestamp()
    metadata = {"voice_session_id": session_id} if voice else {}
    with session.factory() as db:
        db.add(EventRecord(id=source_id, network_id=workspace_id,
                           type="workspace.message.posted", source=f"human:{user_id}",
                           target=target, payload={"content": text, "message_type": "chat"},
                           metadata_=metadata, timestamp=timestamp))
        db.commit()
        move, reply, violations = await run_counselor_turn(db, CounselorTurnInput(
            channel=target, workspace_id=workspace_id, student_text=text,
            attachments=(), session_id=session_id, source_event_id=source_id,
            timestamp=timestamp, source=f"human:{user_id}", voice=voice,
        ))
        db.add(EventRecord(id=str(uuid.uuid4()), network_id=workspace_id,
                           type="workspace.message.posted", source="openagents:pai",
                           target=target, payload={"content": reply, "message_type": "chat"},
                           timestamp=session.next_timestamp()))
        db.commit()
        journey = db.execute(select(StudentJourney).where(
            StudentJourney.workspace_id == workspace_id,
            StudentJourney.journey_type == "counselor_decision",
        )).scalar_one_or_none()
        queued = bool(journey and journey.research_request and journey.research_request.get("status") == "queued")
    return move, reply, violations, queued


async def _run_persona(session, persona, run, *, mode, max_turns, db_lock=None):
    workspace_id, user_id = _workspace(session, persona, run)
    transcript = []
    checks = Counter()
    seen_slots = set()
    student_text = persona["opening"]
    queued = False
    error = None
    previous_segment = 0
    for turn_number in range(max_turns):
        # New targets create real returning sessions without changing student state.
        segment = 0 if turn_number < 5 else 1 if turn_number < 10 else 2 if turn_number < 15 else 3
        if segment != previous_segment:
            session.counter += 24 * 3600 * 1000
            previous_segment = segment
        target = f"channel/sim-{persona['id']}-{run}-{segment}"
        voice = (mode == "voice") or (mode == "switch" and segment % 2 == 1)
        session_id = f"sim-{persona['id']}-{run}-{segment}"
        try:
            if db_lock is None:
                move, reply, violations, queued = await _turn(
                    session, workspace_id, user_id, student_text, target=target,
                    voice=voice, session_id=session_id)
            else:
                async with db_lock:
                    move, reply, violations, queued = await _turn(
                        session, workspace_id, user_id, student_text, target=target,
                        voice=voice, session_id=session_id)
        except Exception as exc:
            checks["error"] = 1
            error = (f"turn {turn_number + 1}: {type(exc).__name__}: {exc}; "
                     + traceback.format_exc(limit=8).replace("\n", " <- "))
            break
        transcript.extend([{"role": "student", "text": student_text, "channel": "voice" if voice else "chat"},
                           {"role": "pai", "text": reply, "move": move.type, "slot": move.slot_key}])
        checks["turns"] += 1
        if move.slot_key and move.slot_key in seen_slots:
            checks["repeat_slot"] += 1
        if move.slot_key:
            seen_slots.add(move.slot_key)
        if deterministic_violations(reply, move, {}, []):
            checks["reply_rule_failure"] += 1
        checks["guard_violations"] += bool(violations)
        if queued:
            checks["queued"] = 1
            break
        try:
            student_text = await _student(persona, transcript, turn_number + 1)
        except Exception as exc:
            checks["error"] = 1
            error = f"student turn {turn_number + 2}: {type(exc).__name__}: {exc}"
            break
    foreign = [item["marker"] for item in PERSONAS if item["id"] != persona["id"]]
    with session.factory() as db:
        candidates = db.execute(select(MemoryCandidate).where(
            MemoryCandidate.workspace_id == workspace_id)).scalars().all()
        memories = db.execute(select(PaiMemory).where(
            PaiMemory.workspace_id == workspace_id)).scalars().all()
        snapshot = StudentSnapshotService(db).build(workspace_id)
        material = json.dumps({"transcript": transcript,
                               "candidates": [row.proposed_value for row in candidates],
                               "memory": [row.content for row in memories],
                               "vault": snapshot.facts, "records": snapshot.records},
                              ensure_ascii=False, default=str)
    checks["leak"] = sum(marker in material for marker in foreign)
    try:
        judge = await _judge(persona, transcript)
    except Exception as exc:
        checks["error"] = 1
        error = f"judge: {type(exc).__name__}: {exc}"
        judge = {"judge_available": False}
    return {"persona": persona["id"], "mode": mode, "run": run,
            "checks": dict(checks), "judge": judge, "transcript": transcript,
            "error": error}


async def evaluate(runs: int, max_turns: int, switch_runs: int, persona_ids=None):
    if not config.PAI_API_KEY:
        raise RuntimeError("PAI_API_KEY is required for model-backed evaluation")
    results = []
    with StudentSession() as session:
        with session.factory() as db:
            _seed_slots(db)
            db.commit()
        selected = [persona for persona in PERSONAS if persona_ids is None or persona["id"] in persona_ids]
        if not selected:
            raise ValueError("No matching persona")
        db_lock = asyncio.Lock()
        for run in range(runs):
            mode = "chat" if run % 2 == 0 else "voice"
            batch = await asyncio.gather(*(
                _run_persona(session, persona, run, mode=mode,
                             max_turns=max_turns, db_lock=db_lock)
                for persona in selected))
            for result in batch:
                results.append(result)
                print(f"{result['persona']} run={run} mode={mode} checks={result['checks']}", flush=True)
        for run in range(switch_runs):
            persona = selected[run % len(selected)]
            result = await _run_persona(session, persona, runs + run,
                                        mode="switch", max_turns=max_turns)
            results.append(result)
            print(f"{persona['id']} switch={run} checks={result['checks']}", flush=True)
    return results


def report(results, path):
    lines = ["# Counselor v2 simulated student evaluation", "",
             f"Runs: {len(results)}", "",
             "| Persona | Mode | Turns | Queued | Repeated slots | Reply rule failures | Leakage | Judge pass | Error |",
             "|---|---|---:|---:|---:|---:|---:|---:|---|"]
    for result in results:
        check = result["checks"]
        lines.append(f"| {result['persona']} | {result['mode']} | {check.get('turns', 0)} | "
                     f"{check.get('queued', 0)} | {check.get('repeat_slot', 0)} | "
                     f"{check.get('reply_rule_failure', 0)} | {check.get('leak', 0)} | "
                     f"{sum(result.get('judge', {}).values())}/{len(result.get('judge', {}))} | "
                     f"{result.get('error') or ''} |")
    lines += ["", "## Pass rate by persona", "",
              "| Persona | Queue | No repeat | Reply rules | No leak | Rubric |",
              "|---|---:|---:|---:|---:|---:|"]
    for persona in dict.fromkeys(row["persona"] for row in results):
        group = [row for row in results if row["persona"] == persona]
        def passed(predicate):
            return f"{sum(bool(predicate(row)) for row in group)}/{len(group)}"
        lines.append(f"| {persona} | {passed(lambda row: row['checks'].get('queued'))} | "
                     f"{passed(lambda row: not row['checks'].get('repeat_slot'))} | "
                     f"{passed(lambda row: not row['checks'].get('reply_rule_failure'))} | "
                     f"{passed(lambda row: not row['checks'].get('leak'))} | "
                     f"{passed(lambda row: all(row.get('judge', {}).values()))} |")
    lines += ["", "## Failing transcripts by check", ""]
    failures = {
        "not_queued": lambda row: not row["checks"].get("queued"),
        "repeated_slot": lambda row: bool(row["checks"].get("repeat_slot")),
        "reply_rule": lambda row: bool(row["checks"].get("reply_rule_failure")),
        "leakage": lambda row: bool(row["checks"].get("leak")),
        "rubric": lambda row: not all(row.get("judge", {}).values()),
    }
    for check, fails in failures.items():
        worst = [row for row in results if fails(row)][:3]
        if not worst:
            continue
        lines += [f"### {check}", ""]
        for result in worst:
            lines += [f"#### {result['persona']} / {result['mode']} / run {result['run']}", ""]
            lines.extend(f"- {turn['role']}" +
                         (f" [{turn.get('move')}/{turn.get('slot')}]" if turn['role'] == 'pai' else '') +
                         f": {turn['text']}" for turn in result["transcript"])
            lines.append("")
    lines += ["", "## Sample transcripts", ""]
    for result in results[:3]:
        lines += [f"### {result['persona']} / {result['mode']} / run {result['run']}", ""]
        lines.extend(f"- {turn['role']}" +
                     (f" [{turn.get('move')}/{turn.get('slot')}]" if turn['role'] == 'pai' else '') +
                     f": {turn['text']}" for turn in result["transcript"])
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true",
                        help="Opt in to the billed model-backed conversation evaluation")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--max-turns", type=int, default=25)
    parser.add_argument("--switch-runs", type=int, default=3)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--persona", action="append", choices=[item["id"] for item in PERSONAS])
    args = parser.parse_args()
    if not args.live:
        from scripts.eval_counselor_research_recorded import evaluate_recorded, report_recorded
        output = args.output or Path("eval_reports") / f"counselor_research_recorded_{datetime.now(timezone.utc):%Y%m%d}.md"
        results = asyncio.run(evaluate_recorded(args.persona))
        report_recorded(results, output)
        print(f"report={output}")
        if any(not all(row["checks"].values()) for row in results):
            sys.exit(1)
        return
    output = args.output or Path("eval_reports") / f"counselor_sim_{datetime.now(timezone.utc):%Y%m%d}.md"
    results = asyncio.run(evaluate(args.runs, args.max_turns, args.switch_runs, args.persona))
    report(results, output)
    print(f"report={output}")
    if any(not item["checks"].get("queued") or item["checks"].get("leak") or
           item["checks"].get("repeat_slot") or item["checks"].get("reply_rule_failure")
           or not all(item.get("judge", {}).values())
           for item in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
