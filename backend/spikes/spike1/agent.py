"""The two readings (SP1-D6): different system prompts, the same output type, the cheap tier.

Invariant 7: the OpenAI client never retries (max_retries=0); answer repair happens only through
output validation, max 2. A reading that still fails is recorded as an error, and its facts stay
unconfirmed.
"""
from __future__ import annotations

from dataclasses import dataclass

from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.os.settings import OsSettings
from spikes.spike1.fields import Reading
from spikes.spike1.pages import PAGE_CHARS, Page
from spikes.spike1.programmes import Programme

AGENT_RETRIES = {"tools": 0, "output": 2}
TOTAL_CHARS = 60_000

_RULES = """
Rules:
- Use only the PAGE texts below. Never use what you know from elsewhere.
- The applicant holds a foreign (non-EU) bachelor's degree and applies for the winter intake.
- For every fact, `quote` must be copied word for word from one page, and `url` must be that page's URL.
- `cycle`: copy the intake or year the page gives for that fact (e.g. "WS 2026/27", "2027"); null if none.
- If the pages do not state a fact, leave it null. Do not guess.
"""

PROMPT_A = "You extract admission facts about one master's programme from official web pages into the given fields." + _RULES

PROMPT_B = (
    "You are checking a study-abroad plan. Answer these questions about one master's programme from "
    "its official pages: Which language is it taught in? Are there tuition fees, and what is the "
    "semester contribution? When does the winter application window open and close for applicants "
    "with a foreign degree? Do they apply through uni-assist, uni-assist VPD then the university, or "
    "directly? What English proof and scores are needed, and is a medium-of-instruction letter enough? "
    "Is German needed? Is there a minimum grade? Is a test such as GRE, GATE or TestAS required? Is "
    "there a summer intake too?" + _RULES
)


def openai_model(settings: OsSettings) -> OpenAIChatModel:
    client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)
    return OpenAIChatModel(settings.model_cheap, provider=OpenAIProvider(openai_client=client))


def build_agents(model: Model) -> dict[str, Agent[None, Reading]]:
    return {name: Agent(model, output_type=Reading, system_prompt=prompt, retries=AGENT_RETRIES, name=f"spike1_{name}")
            for name, prompt in (("A", PROMPT_A), ("B", PROMPT_B))}


def user_prompt(programme: Programme, pages: list[Page]) -> str:
    parts, left = [f"Programme: {programme.programme}\nUniversity: {programme.university}\n"], TOTAL_CHARS
    for p in pages:
        if not p.ok or left <= 0:
            continue
        text = p.text[: min(PAGE_CHARS, left)]
        left -= len(text)
        parts.append(f"=== PAGE {p.url}\n{text}\n")
    return "\n".join(parts)


@dataclass
class ReadingResult:
    reading: Reading | None
    error: str | None
    input_tokens: int
    output_tokens: int
    requests: int


async def read(agent: Agent[None, Reading], prompt: str) -> ReadingResult:
    try:
        r = await agent.run(prompt)
    except Exception as e:  # recorded, not retried (invariant 7)
        return ReadingResult(None, f"{type(e).__name__}: {e}"[:300], 0, 0, 0)
    u = r.usage
    return ReadingResult(r.output, None, u.input_tokens or 0, u.output_tokens or 0, u.requests or 0)
