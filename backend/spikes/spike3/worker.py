"""Spike 3 (throwaway): one chaos worker process.

    python -m spikes.spike3.worker --model {test|openai} [--model-delay 0.5]
        [--executor-id spike3-w0] [--worker-concurrency 2]

Configures DBOS exactly as Task 6 (`loop.start`), then blocks while DBOS polls the `spike3`
queue. The chaos driver starts one worker per slot with a fixed executor ID (`spike3-w{slot}`),
so the replacement for a SIGKILLed worker recovers the workflows its predecessor left PENDING.

Environment: OS_DATABASE_URL (also used as the DBOS system database), OS_DBOS_SYSTEM_SCHEMA,
SPIKE3_WORKER (process label written to step_runs/model_calls), SPIKE3_DRIVER_PID and, for
`--model openai`, OS_OPENAI_API_KEY. Stops on SIGTERM/SIGINT, or when the driver is gone.
"""

import argparse
import asyncio
import os
import re
import signal
import threading

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.os.settings import OsSettings, load_settings
from spikes.spike3 import loop

DEFAULT_MODEL_DELAY_S = 0.5
DEFAULT_WORKER_CONCURRENCY = 2
PAGE_RE = re.compile(r"<page>\n(.*)\n</page>", re.DOTALL)


def _page_in_prompt(messages: list[ModelMessage]) -> str:
    for message in messages:
        if isinstance(message, ModelRequest):
            for part in message.parts:
                if isinstance(part, UserPromptPart) and isinstance(part.content, str):
                    if match := PAGE_RE.search(part.content):
                        return match.group(1)
    raise ValueError("no <page> in the prompt")


def slow_test_model(delay_s: float) -> FunctionModel:
    """Answers after `delay_s` (so kills hit in-flight requests) with a quote copied from the page."""

    async def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        await asyncio.sleep(delay_s)
        lines = [line for line in _page_in_prompt(messages).splitlines() if line.strip()]
        quote = next((line for line in lines if line.startswith("Language requirements:")), lines[0])
        args = {"field": "language_requirement", "value": "see quote", "quote": quote}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, args)])

    return FunctionModel(respond, model_name="spike3-slow-test")


def build_model(name: str, delay_s: float, settings: OsSettings) -> Model:
    if name == "test":
        return slow_test_model(delay_s)
    if not settings.openai_api_key:
        raise SystemExit("--model openai needs OS_OPENAI_API_KEY (the dev key); it is not set")
    return loop.openai_model(settings)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=["test", "openai"], required=True)
    parser.add_argument("--model-delay", type=float, default=DEFAULT_MODEL_DELAY_S, help="test model only (s)")
    parser.add_argument("--executor-id", default=None, help="DBOS executor ID (one per worker slot)")
    parser.add_argument("--worker-concurrency", type=int, default=DEFAULT_WORKER_CONCURRENCY)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = load_settings()
    model = build_model(args.model, args.model_delay, settings)  # fails fast, before DBOS starts

    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    # From the driver, not getppid(): the driver may die while this process is still importing.
    driver_pid = int(os.environ.get("SPIKE3_DRIVER_PID") or os.getppid())

    loop.start(
        database_url=settings.database_url,
        system_database_url=settings.database_url,
        schema=settings.dbos_system_schema,
        model=model,
        executor_id=args.executor_id,
        worker_concurrency=args.worker_concurrency,
    )
    try:
        # DBOS's queue thread does the work; this thread only waits to be stopped.
        while not stop.wait(0.5):
            if os.getppid() != driver_pid:  # the driver died without stopping us: do not linger
                break
    finally:
        loop.shutdown()


if __name__ == "__main__":
    main()
