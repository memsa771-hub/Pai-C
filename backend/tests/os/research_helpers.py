"""Test-only research helpers: programme pages and a fake model that answers from them.

Loaded into worker subprocesses through OS_TEST_RESEARCH_MODEL (`tests.os.research_helpers:slow_model`), so the
crash test runs the real worker with no network and no paid model.
"""

import os
import re
import time

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

PAGES = {
    "tu-chemnitz-embedded-systems": ("https://www.tu-chemnitz.test/es", "tu-chemnitz.test", "Embedded Systems"),
    "ovgu-eeit": ("https://www.ovgu.test/eeit", "ovgu.test", "Electrical Engineering and Information Technology"),
    "btu-artificial-intelligence": ("https://www.b-tu.test/ai", "b-tu.test", "Artificial Intelligence"),
}
DEADLINE = "Application deadline for the winter semester 2027/28: 1 July 2027."
ROUTE = "International applicants apply via uni-assist."
NO_TEST = "There is no admission test."
_URL = re.compile(r"<<<PAGE url=(\S+)>>>")


def page_text(name: str) -> str:
    """The page as the gateway stores it (title line first)."""
    return f"MSc {name} | University\n{DEADLINE}\n{ROUTE}\n{NO_TEST}"


def answer_for(url: str) -> dict:
    return {
        "deadline_close": {"value": "07-01", "quote": DEADLINE, "url": url, "cycle": "winter semester 2027/28"},
        "application_route": {"value": "uni_assist", "quote": ROUTE, "url": url},
        "admission_test": {"value": {"any_of": []}, "quote": NO_TEST, "url": url},
    }


def _answer(messages, info: AgentInfo) -> ModelResponse:
    time.sleep(float(os.environ.get("OS_TEST_MODEL_SLEEP_S", "0")))  # a slow reading, so kills land inside one
    prompt = " ".join(str(p.content) for m in messages for p in m.parts if p.part_kind == "user-prompt")
    found = _URL.search(prompt)
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, answer_for(found.group(1)) if found else {})])


def slow_model() -> FunctionModel:
    return FunctionModel(_answer)
