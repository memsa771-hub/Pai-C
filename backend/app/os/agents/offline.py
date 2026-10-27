"""Offline AI for rehearsals (Slice 9a spec §2.3): canned, repeatable, zero-cost answers.

With `OS_MODEL_MODE=offline` (only allowed in rehearsal mode, see settings) the model router gives each agent a
Pydantic AI `FunctionModel` named "offline" instead of OpenAI. Its answers come only from the YAML files in
`OS_OFFLINE_ANSWERS_DIR`, one per agent (`<agent id>.yaml`); this module holds no answers and no student data
(invariant 12). The agents still validate what comes back (invariant 7): an answer that is missing fails output
validation, so the pipeline records it like any other invalid output, and the missing key is logged here.

- documents: the field values for the first image the reader sends (a page, or a page's first tile), looked up by
  its SHA-256.
- research: every field "not found" (no tools, no page text needed; the workflow's pages come from `OfflinePages`).
- writer: a template per statement kind, filled from the fenced answers and profile values in its prompt, cut to
  the stated word or character limit.
- critic: one passing review, each rubric criterion given the file's score.
- supervisor: the operations for the first event's type, with `{field}` filled from that event's fields.
"""

import hashlib
import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

import yaml
from pydantic_ai import BinaryContent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.os import clock

MODEL_NAME = "offline"
MISSING = "missing_offline_answer"  # not a field of any output model: the answer fails output validation

log = logging.getLogger(__name__)

_ANSWER = re.compile(r"<<<ANSWER question=.*?>>>\n(.*?)\n<<<END>>>", re.S)
_VALUE = re.compile(r"<<<VALUE \S+?>>>\n(.*?)\n<<<END>>>", re.S)
_LIMIT_WORDS = re.compile(r"at most (\d+) words")
_LIMIT_CHARS = re.compile(r"at most (\d+) characters")
_PLAN = re.compile(r"<<<PLAN>>>\n(.*)\n<<<END>>>", re.S)
_FIELD = re.compile(r"\{(\w+)\}")


def _user_content(messages: list[ModelMessage]) -> list:
    """The first user prompt's content, as a list (the agent's input; repair prompts come later)."""
    for m in messages:
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, UserPromptPart):
                    return p.content if isinstance(p.content, list) else [p.content]
    return []


def _user_text(messages: list[ModelMessage]) -> str:
    return "\n".join(c for c in _user_content(messages) if isinstance(c, str))


def _answer(info: AgentInfo, args: dict) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)], model_name=MODEL_NAME)


def _missing(info: AgentInfo, agent_id: str, key: str) -> ModelResponse:
    log.warning("offline answer missing: agent=%s key=%s", agent_id, key)
    return _answer(info, {MISSING: f"{agent_id}:{key}"})


def _documents(answers: dict) -> Callable:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        image = next((c for c in _user_content(messages) if isinstance(c, BinaryContent)), None)
        key = hashlib.sha256(image.data).hexdigest() if image is not None else "no-image"
        entry = answers.get(key)
        return _missing(info, "documents", key) if entry is None else _answer(info, dict(entry["values"]))

    return fn


def _research(answers: dict) -> Callable:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        fields = info.output_tools[0].parameters_json_schema.get("properties", {})
        return _answer(info, {name: answers["not_found"] for name in fields})

    return fn


def _cut(text: str, words: int | None, chars: int | None) -> str:
    if words is not None:
        found = list(re.finditer(r"\S+", text))
        if len(found) > words:
            text = text[: found[words - 1].end()]
    if chars is not None and len(text) > chars:
        text = text[:chars]
        text = text[: text.rfind(" ")] if " " in text else text
    return text.strip()


def _writer(answers: dict) -> Callable:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        from app.os.statements.agents import (
            _KIND,  # imported late: statements imports the model router
        )

        prompt = _user_text(messages)
        first = prompt.split("\n", 1)[0]
        kind = next((k for k, phrase in _KIND.items() if first.startswith(f"Write {phrase},")), None)
        if kind is None or kind not in answers:
            return _missing(info, "writer", str(kind))
        words, chars = _LIMIT_WORDS.search(first), _LIMIT_CHARS.search(first)
        text = answers[kind].format(answers="\n\n".join(a.strip() for a in _ANSWER.findall(prompt)),
                                    profile="; ".join(v.strip() for v in _VALUE.findall(prompt)))
        return _answer(info, {"text": _cut(text, int(words[1]) if words else None, int(chars[1]) if chars else None)})

    return fn


def _critic(answers: dict) -> Callable:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        prompt = _user_text(messages)
        rubric = prompt.split("Rubric:\n", 1)[1].split("\n\n", 1)[0] if "Rubric:\n" in prompt else ""
        criteria = [line[2:].strip() for line in rubric.splitlines() if line.startswith("- ")]
        return _answer(info, {"scores": {c: answers["score"] for c in criteria}, "fixes": list(answers["fixes"]),
                              "follow_ups": list(answers["follow_ups"]), "ok": answers["ok"]})

    return fn


def _fill(value, event: dict):
    if isinstance(value, str):
        return _FIELD.sub(lambda m: str(event.get(m[1], "")), value)
    if isinstance(value, dict):
        return {k: _fill(v, event) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, event) for v in value]
    return value


def _supervisor(answers: dict) -> Callable:
    def fn(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        found = _PLAN.search(_user_text(messages))
        events = json.loads(found[1]).get("events", []) if found else []
        event = events[0] if events else {}
        entry = answers.get(event.get("type"))
        if entry is None:
            return _missing(info, "supervisor", str(event.get("type")))
        return _answer(info, {"ops": _fill(entry["ops"], event), "summary": _fill(entry["summary"], event)})

    return fn


_AGENTS: dict[str, Callable[[dict], Callable]] = {
    "documents": _documents, "research": _research, "writer": _writer, "critic": _critic, "supervisor": _supervisor,
}


def offline_model(agent_id: str, answers_dir: Path) -> FunctionModel:
    """The offline model for one agent, answering from `<answers_dir>/<agent_id>.yaml` (read once, now: a missing or
    broken file stops the worker at startup)."""
    if agent_id not in _AGENTS:
        raise ValueError(f"no offline answers for agent {agent_id!r}")
    path = Path(answers_dir) / f"{agent_id}.yaml"
    answers = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(answers, dict):
        raise ValueError(f"{path}: the offline answers must be a mapping")
    return FunctionModel(_AGENTS[agent_id](answers), model_name=MODEL_NAME)


class OfflinePages:
    """The research workflow's page gateway in offline mode: nothing is fetched or stored. Every page comes back
    blocked as "offline", so the readers see no page text and every fact stays as it is."""

    def fetch(self, url: str, own: list, shared: list):
        from app.os.knowledge.research.pages import Page

        return Page(url=url, blocked=MODEL_NAME, fetched_at=clock.now())

    def record_failure(self, url: str, reason: str):
        from app.os.knowledge.research.pages import Page

        return Page(url=url, blocked=f"error:{reason}", fetched_at=clock.now())
