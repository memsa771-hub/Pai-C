"""Spike 3 (throwaway): the PAI OS core loop.

kernel `mark_ready` -> `enqueue_pending` -> DBOS queue -> `run_attempt` workflow:
load_page -> extract (Pydantic AI agent with DBOSDurability) -> record_result -> complete_task.
The agent's model requests are DBOS steps of `run_attempt` itself (no child workflow).

Importing this module has no side effects. A process uses it like this (Task 7's worker
does the same):

    start(database_url=..., system_database_url=..., schema=..., model=...)
    ...                                   # enqueue_pending / reconcile / wait
    shutdown()

All functions that take `conn` expect a psycopg connection in autocommit mode.
"""

import zlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import psycopg
from dbos import DBOS, DBOSConfig, Queue, SetWorkflowID
from openai import AsyncOpenAI
from psycopg.types.json import Jsonb
from pydantic import BaseModel
from pydantic_ai import Agent, ModelRetry, RunContext
from pydantic_ai.durable_exec.dbos import DBOSDurability, StepConfig
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from app.os.settings import OsSettings

APP_NAME = "pai-os-spike3"
QUEUE_NAME = "spike3"
AGENT_NAME = "spike3_extractor"
SPIKE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = SPIKE_DIR / "schema.sql"
PAGES_DIR = SPIKE_DIR / "pages"

# Invariant 7: network/service retries happen only here, as DBOS step retries.
STEP_CONFIG = StepConfig(retries_allowed=True, max_attempts=3)
# Invariant 7: answer repair happens only through output validation (2 retries).
AGENT_RETRIES = {"tools": 0, "output": 2}

PROMPT = (
    "Extract one fact about this study programme: its application deadline, its tuition, "
    "or its language requirement. Copy `quote` word for word from the page.\n\n"
    "<page>\n{page}\n</page>"
)

# --- SQL (shared by the workflow steps and the kernel-side functions) -------------------

MARK_READY_SQL = """
INSERT INTO spike3.tasks (id, status, attempt) VALUES (%s, 'ready', 1)
ON CONFLICT (id) DO UPDATE
    SET status = 'ready', attempt = spike3.tasks.attempt + 1, failure_reason = NULL
RETURNING attempt
"""
INSERT_ENQUEUE_REQUEST_SQL = "INSERT INTO spike3.enqueue_requests (task_id, attempt) VALUES (%s, %s)"
UNSENT_REQUESTS_SQL = "SELECT task_id, attempt FROM spike3.enqueue_requests WHERE NOT sent ORDER BY task_id, attempt"
MARK_SENT_SQL = "UPDATE spike3.enqueue_requests SET sent = true WHERE task_id = %s AND attempt = %s"
STEP_RUN_SQL = "INSERT INTO spike3.step_runs (task_id, attempt, step) VALUES (%s, %s, %s)"
MODEL_CALL_SQL = "INSERT INTO spike3.model_calls (task_id, attempt) VALUES (%s, %s)"
MARK_RUNNING_SQL = (
    "UPDATE spike3.tasks SET status = 'running' WHERE id = %s AND attempt = %s AND status = 'ready'"
)
# Invariant 8: a re-run of record_result inserts nothing (one row per task attempt).
RECORD_RESULT_SQL = """
INSERT INTO spike3.results (task_id, attempt, output, valid) VALUES (%s, %s, %s, %s)
ON CONFLICT (task_id, attempt) DO NOTHING
"""
# Status changes only apply to the attempt they belong to, and only once.
COMPLETE_TASK_SQL = """
UPDATE spike3.tasks SET status = 'done'
WHERE id = %s AND attempt = %s AND status IN ('ready', 'running')
"""
FAIL_TASK_SQL = """
UPDATE spike3.tasks SET status = 'failed', failure_reason = %s
WHERE id = %s AND attempt = %s AND status IN ('ready', 'running')
"""
OPEN_TASKS_SQL = "SELECT id, attempt, status FROM spike3.tasks WHERE status IN ('ready', 'running') ORDER BY id"
RESULT_VALID_SQL = "SELECT valid FROM spike3.results WHERE task_id = %s AND attempt = %s"


# --- output -------------------------------------------------------------------------


class ProgrammeFact(BaseModel):
    field: Literal["deadline", "tuition", "language_requirement"]
    value: str
    quote: str


@dataclass(frozen=True)
class ExtractDeps:
    """Agent deps: the page the output validator checks quotes against."""

    page_text: str


# (task_id, attempt) of the running attempt, for the model_calls counter. run_attempt sets it
# from its own arguments, which DBOS checkpoints, so every execution of the workflow body
# (first run or recovery) sets it before any model step runs.
current_attempt: ContextVar[tuple[str, int] | None] = ContextVar("spike3_current_attempt", default=None)


def quote_on_page(ctx: RunContext[ExtractDeps], output: ProgrammeFact) -> ProgrammeFact:
    if not output.quote.strip() or output.quote not in ctx.deps.page_text:
        raise ModelRetry("`quote` must be copied word for word from the page.")
    return output


# --- pages ----------------------------------------------------------------------------


def page_paths() -> list[Path]:
    return sorted(PAGES_DIR.glob("*.txt"))


def page_for(task_id: str) -> Path:
    """Stable across processes (crc32, not the salted built-in hash)."""
    paths = page_paths()
    return paths[zlib.crc32(task_id.encode("utf-8")) % len(paths)]


# --- runtime state --------------------------------------------------------------------


@dataclass
class _Runtime:
    database_url: str
    agent: Agent[ExtractDeps, ProgrammeFact]
    load_page: Any
    record_result: Any
    complete_task: Any
    fail_task: Any
    run_attempt: Any
    queue: Queue | None = None


_runtime: _Runtime | None = None


def _rt() -> _Runtime:
    if _runtime is None:
        raise RuntimeError("spike3 loop is not registered; call start() first")
    return _runtime


@asynccontextmanager
async def _connect() -> AsyncIterator[psycopg.AsyncConnection]:
    async with await psycopg.AsyncConnection.connect(_rt().database_url, autocommit=True) as conn:
        yield conn


def workflow_id(task_id: str, attempt: int) -> str:
    return f"{task_id}:{attempt}"


# --- model and agent ------------------------------------------------------------------


class CountingModel(WrapperModel):
    """Writes one `model_calls` row per model request, then forwards the request.

    Runs inside the DBOS model step, so it counts every real request (including step
    retries) and nothing when a finished step is replayed from its checkpoint.
    """

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        attempt = current_attempt.get()
        if attempt is None:
            raise RuntimeError("CountingModel runs only inside run_attempt")
        async with _connect() as conn:
            await conn.execute(MODEL_CALL_SQL, attempt)
        return await super().request(messages, model_settings, model_request_parameters)


def openai_model(settings: OsSettings) -> OpenAIChatModel:
    # Invariant 7: the client never retries on its own; DBOS step retries do.
    client = AsyncOpenAI(api_key=settings.openai_api_key, max_retries=0)
    return OpenAIChatModel(settings.model_cheap, provider=OpenAIProvider(openai_client=client))


def build_agent(model: Model) -> Agent[ExtractDeps, ProgrammeFact]:
    """Must run before DBOS.launch(): DBOSDurability registers the model steps when bound."""
    agent = Agent(
        CountingModel(model),
        output_type=ProgrammeFact,
        deps_type=ExtractDeps,
        retries=AGENT_RETRIES,
        name=AGENT_NAME,
        capabilities=[DBOSDurability(model_step_config=STEP_CONFIG)],
    )
    agent.output_validator(quote_on_page)
    return agent


# --- workflow steps -------------------------------------------------------------------
# Each step first appends a step_runs row (counts re-runs), then does an idempotent write.


async def load_page(task_id: str, attempt: int) -> str:
    async with _connect() as conn:
        await conn.execute(STEP_RUN_SQL, (task_id, attempt, "load_page"))
        await conn.execute(MARK_RUNNING_SQL, (task_id, attempt))
    return page_for(task_id).read_text(encoding="utf-8")


async def record_result(task_id: str, attempt: int, output: dict[str, Any] | None, valid: bool) -> None:
    async with _connect() as conn:
        await conn.execute(STEP_RUN_SQL, (task_id, attempt, "record_result"))
        stored = None if output is None else Jsonb(output)
        await conn.execute(RECORD_RESULT_SQL, (task_id, attempt, stored, valid))


async def complete_task(task_id: str, attempt: int) -> None:
    async with _connect() as conn:
        await conn.execute(STEP_RUN_SQL, (task_id, attempt, "complete_task"))
        await conn.execute(COMPLETE_TASK_SQL, (task_id, attempt))


async def fail_task(task_id: str, attempt: int, reason: str) -> None:
    async with _connect() as conn:
        await conn.execute(STEP_RUN_SQL, (task_id, attempt, "fail_task"))
        await conn.execute(FAIL_TASK_SQL, (reason, task_id, attempt))


async def run_attempt(task_id: str, attempt: int) -> None:
    """Workflow body, registered as `spike3.run_attempt` by register()."""
    rt = _rt()
    page = await rt.load_page(task_id, attempt)
    token = current_attempt.set((task_id, attempt))
    try:
        result = await rt.agent.run(PROMPT.format(page=page), deps=ExtractDeps(page_text=page))
    except UnexpectedModelBehavior:
        # Output retries are used up. Record it and stop; the kernel decides what happens next.
        await rt.record_result(task_id, attempt, None, False)
        await rt.fail_task(task_id, attempt, "invalid_output")
        return
    finally:
        current_attempt.reset(token)
    await rt.record_result(task_id, attempt, result.output.model_dump(), True)
    await rt.complete_task(task_id, attempt)


# --- DBOS lifecycle -------------------------------------------------------------------


def dbos_config(system_database_url: str, schema: str) -> DBOSConfig:
    return {"name": APP_NAME, "system_database_url": system_database_url, "dbos_system_schema": schema}


def register(database_url: str, agent: Agent[ExtractDeps, ProgrammeFact]) -> None:
    """Registers the steps and the workflow with the current DBOS registry (before launch).

    Done here, not with module-level decorators: DBOS wrappers keep a reference to the
    registry they were made in, and shutdown() destroys that registry so a second runtime
    (another model) can start in the same process. The agent's model steps were registered
    by build_agent() in the same registry.
    """
    global _runtime

    def step(fn: Any) -> Any:
        return DBOS.step(name=f"spike3.{fn.__name__}", **STEP_CONFIG)(fn)

    _runtime = _Runtime(
        database_url=database_url,
        agent=agent,
        load_page=step(load_page),
        record_result=step(record_result),
        complete_task=step(complete_task),
        fail_task=step(fail_task),
        run_attempt=DBOS.workflow(name="spike3.run_attempt")(run_attempt),
    )


def launch() -> None:
    DBOS.launch()
    _rt().queue = DBOS.register_queue(QUEUE_NAME)


def start(*, database_url: str, system_database_url: str, schema: str, model: Model) -> None:
    """Configures DBOS, builds the agent, registers everything and launches."""
    DBOS(config=dbos_config(system_database_url, schema))
    register(database_url, build_agent(model))
    launch()


def shutdown() -> None:
    global _runtime
    DBOS.destroy(destroy_registry=True)
    _runtime = None


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


# --- kernel side ----------------------------------------------------------------------


def mark_ready(conn: psycopg.Connection, task_id: str) -> None:
    """One transaction: status ready, attempt += 1, enqueue request for that attempt."""
    with conn.transaction():
        row = conn.execute(MARK_READY_SQL, (task_id,)).fetchone()
        assert row is not None
        conn.execute(INSERT_ENQUEUE_REQUEST_SQL, (task_id, row[0]))


def _enqueue(conn: psycopg.Connection, task_id: str, attempt: int) -> None:
    rt = _rt()
    assert rt.queue is not None, "launch() registers the queue"
    # The workflow ID is the idempotency key: a second enqueue of it is the same workflow.
    with SetWorkflowID(workflow_id(task_id, attempt)):
        rt.queue.enqueue(rt.run_attempt, task_id, attempt)
    conn.execute(MARK_SENT_SQL, (task_id, attempt))


def enqueue_pending(conn: psycopg.Connection) -> int:
    """Enqueues every unsent request. A crash before `sent` is set only causes a harmless re-enqueue."""
    rows = conn.execute(UNSENT_REQUESTS_SQL).fetchall()
    for task_id, attempt in rows:
        _enqueue(conn, task_id, attempt)
    return len(rows)


def _apply_result(conn: psycopg.Connection, task_id: str, attempt: int) -> bool:
    row = conn.execute(RESULT_VALID_SQL, (task_id, attempt)).fetchone()
    if row is None:
        return False
    if row[0]:
        cur = conn.execute(COMPLETE_TASK_SQL, (task_id, attempt))
    else:
        cur = conn.execute(FAIL_TASK_SQL, ("invalid_output", task_id, attempt))
    return cur.rowcount == 1


def reconcile(conn: psycopg.Connection) -> dict[str, int]:
    """Repairs what a crash between the loop's steps can leave behind.

    - a `ready` task whose workflow DBOS has never seen: enqueue it (same workflow ID);
    - a `ready`/`running` task whose workflow succeeded: apply its recorded result.

    `present` counts open tasks whose workflow DBOS already knows (in any status).
    """
    counts = {"reenqueued": 0, "present": 0, "applied": 0}
    for task_id, attempt, status in conn.execute(OPEN_TASKS_SQL).fetchall():
        wf = DBOS.get_workflow_status(workflow_id(task_id, attempt))
        if wf is None:
            if status == "ready":
                _enqueue(conn, task_id, attempt)
                counts["reenqueued"] += 1
        else:
            counts["present"] += 1
            if wf.status == "SUCCESS" and _apply_result(conn, task_id, attempt):
                counts["applied"] += 1
    return counts
