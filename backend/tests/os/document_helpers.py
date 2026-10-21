"""Test-only document helpers: a slow fake reader model for the crash test.

Loaded into worker subprocesses through OS_TEST_DOCUMENT_MODEL (`tests.os.document_helpers:slow_model`), so the
crash test runs the real worker with no network and no paid model. Fictional values only.
"""

import os
import time

from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

ANSWER = {"student_name": "Sara Ahmed Khan", "father_name": "Ahmed Raza Khan", "date_of_birth": "2001-04-12",
          "institution": "University of Exampleton", "cgpa": 3.4, "cgpa_scale": 4.0, "detected_type": "transcript"}


def _answer(messages, info: AgentInfo) -> ModelResponse:
    time.sleep(float(os.environ.get("OS_TEST_MODEL_SLEEP_S", "0")))  # a slow reading, so kills land inside one
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, ANSWER)])


def slow_model() -> FunctionModel:
    return FunctionModel(_answer)
