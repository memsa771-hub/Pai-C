"""Check every student-facing Counselor reply before it is posted."""

import json
import logging
import unicodedata
from difflib import SequenceMatcher

from app.config import config
from app.inference.client import chat_completion
from .turn_contract import parse_turn

logger = logging.getLogger(__name__)
DONE = frozenset({"answered", "valid_unknown", "not_applicable", "declined",
                  "pending", "deferred"})


def _fallback(question: str | None) -> str:
    return ("I hear what you want to work on, and I'll keep it in view. "
            + (question or "Tell me which part you want to work through first."))


def _questions(text: str) -> list[str]:
    """Question punctuation across scripts without a language dictionary."""
    parts, start = [], 0
    for index, char in enumerate(text):
        if "QUESTION MARK" in unicodedata.name(char, ""):
            parts.append(text[start:index + 1].strip())
            start = index + 1
    return parts


def _comparable(text: str) -> str:
    return " ".join("".join(char.casefold() if char.isalnum() else " " for char in text).split())


def deterministic_issues(reply: str, *, max_questions: int = 1,
                         word_budget: int = 120,
                         requirement_fields: list[dict] | None = None) -> list[str]:
    """Cheap hard limits; meaning and source quality remain the model check's job."""
    issues = []
    questions = _questions(reply)
    if len(questions) > max_questions:
        issues.append("too_many_questions")
    if len(reply.split()) > word_budget:
        issues.append("too_long")
    blocked = [_comparable(item.get("question") or "")
               for item in (requirement_fields or []) if item.get("status") in DONE]
    for question in questions:
        comparable = _comparable(question)
        if comparable and any(candidate and (
                candidate in comparable or SequenceMatcher(None, candidate, comparable).ratio() >= 0.88)
                for candidate in blocked):
            issues.append("reasks_known_or_pending")
            break
    return issues


async def guard_reply(reply: str, *, student_message: str, mode: str,
                      question: str | None = None, max_questions: int = 1,
                      requirement_fields: list[dict] | None = None,
                      allow_long: bool = False) -> str:
    """Apply hard checks, semantic review, one rewrite, and a safe fallback."""
    budget = 320 if allow_long else 120
    hard_issues = deterministic_issues(
        reply, max_questions=max_questions, word_budget=budget,
        requirement_fields=requirement_fields)
    try:
        raw = await chat_completion(
            api_key=config.PAI_API_KEY, model=config.PAI_MODEL,
            base_url=config.PAI_BASE_URL or None, reasoning_effort="low",
            max_tokens=900,
            system_prompt=(
                "Review the student-facing Counselor reply. Return JSON only: "
                '{"allowed": boolean, "reply": string}. '
                "Answer the student's actual request first in their language. Use at most "
                "one useful question and do not re-ask any known or pending profile item. "
                "Keep the reply short unless detail was requested. Do not reveal internal "
                "state, tool names, JSON, or policy. Do not state unsourced eligibility, "
                "requirements, fees, deadlines, or recognition as facts. "
                "In collecting mode, allow general help but no personalized verdict. "
                "If the draft violates a rule, rewrite it naturally within the supplied "
                "limits. If allowed, copy it unchanged. Never mention this review."
            ),
            messages=[{"role": "user", "content": json.dumps({
                "student_message": student_message[:4000], "draft": reply[:5000],
                "mode": mode, "hard_issues": hard_issues,
                "max_questions": max_questions, "word_budget": budget,
                "allowed_question": question,
                "known_or_pending_questions": [item.get("question")
                    for item in (requirement_fields or []) if item.get("status") in DONE],
            }, ensure_ascii=False)}],
        )
        text = (raw or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        if not isinstance(result, dict) or not isinstance(result.get("allowed"), bool):
            raise ValueError("Invalid Counselor review")
        if result["allowed"] and not hard_issues:
            return reply
        candidate = result.get("reply")
        if isinstance(candidate, str) and candidate.strip():
            visible, _ = parse_turn(candidate)
            if visible and visible == candidate.strip() and not deterministic_issues(
                    visible, max_questions=max_questions, word_budget=budget,
                    requirement_fields=requirement_fields):
                return visible
    except Exception:
        logger.warning("counselor: reply review unavailable", exc_info=True)
    return _fallback(question)


async def guard_collection_reply(reply: str, *, student_message: str,
                                 question: str | None) -> str:
    """Compatibility entry point for callers already using the collection guard."""
    return await guard_reply(reply, student_message=student_message,
                             mode="collecting", question=question)
