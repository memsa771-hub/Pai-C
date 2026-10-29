"""One durable opening after onboarding, delivered through the Messenger."""
import json
import logging
from pathlib import Path

from sqlalchemy import select

from app.config import config
from app.inference import usage
from app.inference.gateway import complete
from app.models import EventRecord, User, Workspace
from app.pai_c.deep.analysis import _workspace_lock
from app.pai_c.deep.context import build_context
from app.pai_c.deep.polish import contains_blocked_script
from app.pai_c.deep.prompts import load_prompt
from app.pai_c.deep.turn_input import CounselorTurnInput
from app.pai_c.posting import send_to_student
from app.services.pai import PAI_AGENT_NAME, PAI_PRIMARY_CHANNEL

JOB_OPENING = "counselor.opening"
logger = logging.getLogger(__name__)


class _Paused(Exception):
    pass


def student_core(db, workspace_id: str, name: str) -> dict:
    """What onboarding already told PAI (BETA_CONVERSATION_SPEC 2.1): the name,
    the education line as the Mirror header builds it, and the other Vault
    facts (status, city, ...) as catalog labels and display text. Restricted
    facts never."""
    from app.pai_c.memory import MemoryService
    from app.pai_c.mirror.engine import MirrorEngine
    header = MirrorEngine(db).build(workspace_id)["header"]
    facts = {row.entry["label"]: row.entry["display"] for row in MemoryService(db).vault_rows(workspace_id)
             if row.entry["kind"] == "fact" and row.sensitivity != "restricted" and row.entry["display"]}
    line = header.get("education_line")
    return {"name": header.get("name") or name, "education_line": line["text"] if line else None,
            "facts": facts}


def opening_language(db, workspace_id: str, words: list[str]) -> dict | None:
    """The chat language when known; else only the script of the student's own
    onboarding words ({code: None, script}), never a guessed language; else
    None (English)."""
    from app.pai_c.language import chat_language, script_of
    known = chat_language(db, workspace_id)
    return known if known is not None else script_of(" ".join(words))


def _already_posted(db, workspace_id, channel):
    return db.scalar(select(EventRecord.id).where(
        EventRecord.network_id == workspace_id,
        EventRecord.target == channel,
        EventRecord.source == f"openagents:{PAI_AGENT_NAME}",
        EventRecord.type == "workspace.message.posted",
    ).limit(1)) is not None


async def opening_job(job, db):
    workspace_id, job_id = job.workspace_id, job.id
    final_attempt = job.attempts >= job.max_attempts
    channel = f"channel/{PAI_PRIMARY_CHANNEL}"
    async with _workspace_lock(db, workspace_id):
        if _already_posted(db, workspace_id, channel):
            return {"status": "already_posted"}
        workspace = db.get(Workspace, workspace_id)
        user = db.get(User, workspace.owner_user_id) if workspace else None
        if user is None or user.onboarded_at is None:
            return {"status": "not_onboarded"}
        name = user.display_name or ""
        turn = CounselorTurnInput(channel, workspace_id, "", (), None,
                                  job_id, None, "system:opening")
        context = await build_context(db, workspace_id, turn)
        core = student_core(db, workspace_id, name)
        from app.pai_c.memory import onboarding_words
        words = onboarding_words(db, workspace_id)
        language = opening_language(db, workspace_id, words)
        from app.pai_c.policy.controller import bank_item, load_data
        about_you = bank_item(load_data("question_bank.json")["first_item"])["prompt"]
        instruction = (Path(__file__).parent / "policy/actions/opening.md").read_text(
            encoding="utf-8").replace("{about_you}", about_you)
        sections = ("<student_core>" + json.dumps(core, ensure_ascii=False) + "</student_core>\n"
                    + "<student_words>" + json.dumps(words, ensure_ascii=False) + "</student_words>\n"
                    + "<opening_language>" + json.dumps(language) + "</opening_language>")
        db.rollback()
        opening_step = None
        try:
            if not usage.role_allowed("counselor"):
                raise _Paused()
            raw = await complete("counselor", messages=[],
                system_prompt=load_prompt("voice") + "\n\n" + context.text + "\n\n" + sections + "\n\n" + instruction,
                response_format={"type": "json_object"}, phase="opening", turn_id=job_id)
            from app.pai_c.deep.turn import unfence
            data = json.loads(unfence(raw))
            reply = data.get("reply") if isinstance(data, dict) else None
            step = data.get("next_step") if isinstance(data, dict) else None
            # One question: the opening ends with its own question; a step is
            # added only to a body that asks none, and at most one question stays.
            from app.pai_c.deep.polish import polish_reply, question_count
            if (isinstance(reply, str) and isinstance(step, str) and step.strip()
                    and not question_count(reply)):
                reply = reply.rstrip() + "\n\n" + step.strip()
                opening_step = step.strip()
            if isinstance(reply, str):
                reply = polish_reply(reply)
                if opening_step and not reply.rstrip().endswith(opening_step):
                    opening_step = None
            if not isinstance(reply, str) or not reply.strip() or contains_blocked_script(
                    reply, config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
                raise ValueError("Invalid opening reply")
        except _Paused:
            # Monthly cap reached: only the paused line (no invitation to talk), no model call.
            from app.pai_c.language import paused_reply
            reply = await paused_reply(db, workspace_id)
            opening_step = None
        except Exception as exc:
            logger.warning("counselor_opening_error job_id=%s error_type=%s", job_id, type(exc).__name__)
            if not final_attempt:
                raise
            reply = config.PAI_OPENING_FALLBACK_REPLY.replace("{name}", name)
            opening_step = None
        # Another normal reply may have arrived while the model was running.
        if _already_posted(db, workspace_id, channel):
            return {"status": "already_posted"}
        posted = await send_to_student(db, workspace_id, channel, PAI_AGENT_NAME,
                                       reply.strip(), 0,
                                       metadata={"next_step": opening_step} if opening_step else None)
        if not posted:
            raise RuntimeError("Opening was not posted")
        return {"status": "posted", "event_id": posted}
