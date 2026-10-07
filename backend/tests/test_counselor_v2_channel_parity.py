"""Voice transcripts and chat share pending answers and the same move planner."""

import uuid

import pytest

from app.counseling.extraction import SlotClaim, TurnExtraction
from app.counseling.turn import CounselorTurnInput, run_counselor_turn
from app.models import CounselorTurnDecision, EventRecord
from sqlalchemy import select
from scripts.counselor_eval_support import StudentSession
from scripts.eval_counselor_sim import _seed_slots


@pytest.mark.asyncio
async def test_two_voice_answers_then_chat_asks_third_slot(monkeypatch):
    async def scope(*args, **kwargs):
        return "in_scope"

    async def extract(text, *args, **kwargs):
        claims = {
            "FSc": (SlotClaim("recent_qualification", {"qualification_name": "FSc"}, .95, "FSc"),),
            "Pre-Engineering": (SlotClaim("qualification_group", "Pre-Engineering", .95,
                                          "Pre-Engineering"),),
            "hello": (),
        }[text]
        return TurnExtraction(claims, "", "none", "en", ())

    async def writer(*, move, requirements, **kwargs):
        row = next((item for item in requirements
                    if item.key == f"discovery.{move.slot_key}"), None)
        return row.canonical_questions["en"] if row else "I hear you."

    async def guard(*, reply, **kwargs):
        return reply, ()

    monkeypatch.setattr("app.counseling.turn.classify_scope", scope)
    monkeypatch.setattr("app.counseling.turn.extract_turn", extract)
    with StudentSession() as student:
        with student.factory() as db:
            _seed_slots(db)
            db.commit()
        keys = []
        for index, (text, voice) in enumerate((("FSc", True), ("Pre-Engineering", True),
                                                ("hello", False))):
            target = "channel/voice" if voice else "channel/chat"
            event_id = str(uuid.uuid4())
            timestamp = student.next_timestamp()
            with student.factory() as db:
                db.add(EventRecord(id=event_id, network_id=student.workspace_id,
                                   type="workspace.message.posted",
                                   source=f"human:{student.user_id}", target=target,
                                   payload={"content": text, "message_type": "chat"},
                                   timestamp=timestamp))
                db.commit()
                move, reply, violations = await run_counselor_turn(
                    db, CounselorTurnInput(
                        channel=target, workspace_id=student.workspace_id,
                        student_text=text, attachments=(),
                        session_id="live-1" if voice else "chat-2",
                        source_event_id=event_id, timestamp=timestamp,
                        source=f"human:{student.user_id}", voice=voice),
                    writer=writer, guard=guard,
                )
                keys.append(move.slot_key)
                db.add(EventRecord(id=str(uuid.uuid4()), network_id=student.workspace_id,
                                   type="workspace.message.posted", source="openagents:pai",
                                   target=target, payload={"content": reply},
                                   timestamp=student.next_timestamp()))
                db.commit()
        assert keys == ["qualification_group", "academic_result", "academic_result"]
        assert keys[2] not in {"recent_qualification", "qualification_group"}
        with student.factory() as db:
            assert len(db.execute(select(CounselorTurnDecision).where(
                CounselorTurnDecision.workspace_id == student.workspace_id)).scalars().all()) == 3
            assert not db.execute(select(EventRecord).where(
                EventRecord.type == "counselor.turn.decision")).scalars().all()


@pytest.mark.asyncio
async def test_same_input_yields_same_approved_words_for_chat_and_voice(monkeypatch):
    async def scope(*args, **kwargs):
        return "in_scope"

    async def extract(*args, **kwargs):
        return TurnExtraction((), "", "none", "en", ())

    async def writer(*, move, requirements, **kwargs):
        row = next(item for item in requirements if item.key == f"discovery.{move.slot_key}")
        return row.canonical_questions["en"]

    async def guard(*, reply, **kwargs):
        return reply, ()

    monkeypatch.setattr("app.counseling.turn.classify_scope", scope)
    monkeypatch.setattr("app.counseling.turn.extract_turn", extract)
    results = []
    for voice in (False, True):
        with StudentSession() as student:
            with student.factory() as db:
                _seed_slots(db)
                event_id = str(uuid.uuid4())
                timestamp = student.next_timestamp()
                db.add(EventRecord(id=event_id, network_id=student.workspace_id,
                                   type="workspace.message.posted",
                                   source=f"human:{student.user_id}", target="channel/pai",
                                   payload={"content": "hello"}, timestamp=timestamp))
                db.commit()
                move, reply, _ = await run_counselor_turn(
                    db, CounselorTurnInput("channel/pai", student.workspace_id,
                                           "hello", (), None, event_id, timestamp,
                                           f"human:{student.user_id}", voice=voice),
                    writer=writer, guard=guard,
                )
                results.append((move, reply))
    assert results[0] == results[1]
