"""The os.statement workflow (Slice 5 spec S5-D6): one SOP or CV draft for one student.

start (budget, status `drafting`) -> load the inputs (one student's answers and allowed profile values, the rules) ->
Writer -> facts check -> Critic -> at most 2 revisions -> store a version. When the Critic asks follow-up questions,
they go to the student and the artifact waits (`needs_answers`); answering them drafts again (S5-D3). Each model
request is a DBOS step (DBOSDurability) and each reading an os_agent_runs row. The workflow ID carries the inputs'
hash, so the same inputs are never drafted twice (invariant 8).
"""

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import datetime

from dbos import DBOS, DBOSClient, EnqueueOptions
from sqlalchemy import Engine, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import clock, models
from app.os.agents.spec import AgentSpec
from app.os.artifacts.store import ArtifactStore
from app.os.documents.store import ProfileStore
from app.os.knowledge.programmes import ProgrammeStore
from app.os.knowledge.research.readings import AgentRuns, cost
from app.os.settings import OsSettings
from app.os.statements.agents import Inputs, review, write
from app.os.statements.config import StatementConfig
from app.os.statements.facts_check import unsupported
from app.os.statements.rules import Rules, resolve_rules

STATEMENT_WORKFLOW = "os.statement"
MAX_REVISIONS = 2
ANS = models.statement_answers


def statement_workflow_id(tenant_id: str, artifact_id: int, inputs_sha: str, attempt: int = 1) -> str:
    """The same inputs give the same ID (invariant 8); `attempt` grows only when the last run ended `failed` or
    `budget`, so "Write again" after those runs again (final review)."""
    return f"statement:{tenant_id}:{artifact_id}:{inputs_sha[:16]}:{attempt}"


def inputs_for(engine: Engine, tenant_id: str, cfg: StatementConfig, student_ref: str, kind: str,
               programme_ref: str | None, knowledge, year: int) -> Inputs:
    """Only this student's material: their answered questions (route and follow-up) and the profile values this kind
    may use. Nothing from another student can reach the Writer."""
    with engine.connect() as conn:
        rows = conn.execute(select(ANS.c.question_id, ANS.c.question, ANS.c.answer).where(
            ANS.c.tenant_id == tenant_id, ANS.c.student_ref == student_ref).order_by(ANS.c.id)).all()
    answers = {}
    for r in rows:
        if not (r.answer or "").strip():
            continue
        q = cfg.question(r.question_id)
        answers[q.prompt if q else (r.question or r.question_id)] = r.answer.strip()
    allowed = set(cfg.kinds[kind].profile_keys)
    profile = {v["key"]: v["value"] for v in ProfileStore(engine, tenant_id).all(student_ref) if v["key"] in allowed}
    rules = resolve_rules(engine, tenant_id, knowledge, student_ref, programme_ref, year, cfg, kind)
    allowed = list(cfg.allowed_names)
    programme = ProgrammeStore(engine, tenant_id).get(programme_ref) if programme_ref else None
    if programme is not None:  # a programme's own statement may name it and its university
        allowed += [programme.university, programme.name]
    return Inputs(kind, answers, profile, rules, list(cfg.kinds[kind].rubric.criteria), allowed)


def inputs_sha(inputs: Inputs) -> str:
    blob = json.dumps(asdict(inputs), sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def sources(inputs: Inputs) -> list[str]:
    """What a claim may come from: the answers (with their questions), the profile values, the programme's prompt."""
    out = [f"{q} {a}" for q, a in inputs.answers.items()]
    out += [f"{k}: {v}" for k, v in inputs.profile.items()]
    return out + ([inputs.rules.prompt] if inputs.rules.prompt else []) + list(inputs.allowed)


def enqueue_statement(client: DBOSClient, tenant_id: str, artifact_id: int, route_key: str, year: int,
                      sha: str, attempt: int = 1) -> str:
    from app.os.runner.workflow import APP_VERSION, QUEUE_NAME  # imported here: the runner imports statements

    wid = statement_workflow_id(tenant_id, artifact_id, sha, attempt)
    options: EnqueueOptions = {"queue_name": QUEUE_NAME, "workflow_name": STATEMENT_WORKFLOW, "workflow_id": wid,
                               "app_version": APP_VERSION}
    client.enqueue(options, artifact_id, route_key, year)
    return wid


def _inputs_from(d: dict) -> Inputs:
    return Inputs(d["kind"], d["answers"], d["profile"], Rules(**d["rules"]), d["rubric"], d.get("allowed", []))


def register_statements(engine: Engine, settings: OsSettings, writer, critic, writer_spec: AgentSpec,
                        critic_spec: AgentSpec, configs: Mapping[str, StatementConfig], knowledge,
                        clock: Callable[[], datetime] = clock.now) -> None:
    """Registers os.statement and its steps. Must run before DBOS.launch(), with the agents built once per process."""
    from app.os.runner.workflow import STEP_CONFIG  # imported here: the runner imports statements

    tenant = settings.tenant_id
    store, runs = ArtifactStore(engine, tenant), AgentRuns(engine, tenant)

    def start(artifact_id: int) -> dict:
        art = store.get(artifact_id)
        if art is None:
            return {"status": "skipped"}
        now = clock()
        spent = runs.month_spend(now, writer_spec.id) + runs.month_spend(now, critic_spec.id)
        if spent >= settings.statements_monthly_usd:
            with engine.begin() as conn:
                conn.execute(insert(models.events).values(tenant_id=tenant, type="budget_exceeded", payload={
                    "tenant_id": tenant, "artifact_id": artifact_id, "spent_usd": spent,
                    "cap_usd": settings.statements_monthly_usd}))
            store.set_status(artifact_id, "budget")  # the student sees it; "Write again" starts a new attempt
            return {"status": "budget"}
        store.set_status(artifact_id, "drafting")
        return {"status": "drafting", "student_ref": art.student_ref, "kind": art.kind,
                "programme_ref": art.programme_ref}

    def load(student_ref: str, kind: str, programme_ref: str | None, route_key: str, year: int) -> dict:
        return asdict(inputs_for(engine, tenant, configs[route_key], student_ref, kind, programme_ref, knowledge, year))

    def record(artifact_id: int, reading: str, spec_id: str, model: str, usage: dict, cost_usd: float,
               error: str | None) -> None:
        from pydantic_ai.usage import RunUsage

        spec = writer_spec if spec_id == writer_spec.id else critic_spec
        runs.record(None, reading, artifact_id=artifact_id, spec=spec, model=model, usage=RunUsage(**usage),
                    cost_usd=cost_usd, error=error)

    def ask(student_ref: str, artifact_id: int, questions: list[str]) -> None:
        with engine.begin() as conn:
            n = len(conn.execute(select(ANS.c.id).where(ANS.c.tenant_id == tenant, ANS.c.student_ref == student_ref,
                                                         ANS.c.question_id.like("followup:%"))).all())
            for i, q in enumerate(questions, n + 1):
                conn.execute(pg_insert(ANS).values(tenant_id=tenant, student_ref=student_ref,
                                                   question_id=f"followup:{i}", question=q, answer="")
                             .on_conflict_do_nothing(constraint="uq_os_statement_answers"))
        store.set_status(artifact_id, "needs_answers")

    def save(artifact_id: int, text: str, critic: dict | None, flags: list[str], limit_words: int | None) -> int:
        return store.add_version(artifact_id, text, "writer", critic=critic, flags=flags, limit_words=limit_words).number

    def fail(artifact_id: int) -> None:
        store.set_status(artifact_id, "failed")

    step = lambda name, fn: DBOS.step(name=f"os.statement.{name}", **STEP_CONFIG)(fn)  # noqa: E731
    start_step, load_step, record_step = step("start", start), step("load", load), step("record", record)
    ask_step, save_step, fail_step = step("ask", ask), step("store", save), step("fail", fail)

    def run_agent(fn, agent, spec, artifact_id: int, label: str, *args):
        result = fn(agent, spec, *args)
        usage = {"input_tokens": result.usage.input_tokens or 0, "cache_read_tokens": result.usage.cache_read_tokens or 0,
                 "output_tokens": result.usage.output_tokens or 0, "requests": result.usage.requests or 0}
        error = None if result.error is None else result.error.split(":", 1)[0]  # the kind only: no student text
        record_step(artifact_id, f"{DBOS.workflow_id}:{label}", spec.id, agent.model.model_name, usage,
                    cost(result.usage, settings, spec.tier), error)
        return result.output

    def statement(artifact_id: int, route_key: str, year: int) -> dict:
        begun = start_step(artifact_id)
        if begun["status"] != "drafting":
            return begun
        inputs = _inputs_from(load_step(begun["student_ref"], begun["kind"], begun["programme_ref"], route_key, year))
        src = sources(inputs)
        draft = run_agent(write, writer, writer_spec, artifact_id, "write:0", inputs)
        if draft is None:
            fail_step(artifact_id)
            return {"status": "failed"}
        text, report = draft.text, None
        flags = [c.text for c in unsupported(text, src)]
        for revision in range(MAX_REVISIONS + 1):
            rev = run_agent(review, critic, critic_spec, artifact_id, f"review:{revision}", inputs, text, flags)
            if rev is None:
                break  # no review: the draft is still the student's to see, with its flags
            report = rev.model_dump()
            if rev.follow_ups:
                save_step(artifact_id, text, report, flags, inputs.rules.limit_words)
                ask_step(begun["student_ref"], artifact_id, rev.follow_ups)
                return {"status": "needs_answers"}
            if (rev.ok and not flags) or revision == MAX_REVISIONS:
                break
            redraft = run_agent(write, writer, writer_spec, artifact_id, f"write:{revision + 1}", inputs, text,
                                rev.fixes, flags)
            if redraft is None:
                break
            text = redraft.text
            flags = [c.text for c in unsupported(text, src)]
        number = save_step(artifact_id, text, report, flags, inputs.rules.limit_words)
        return {"status": "draft", "version": number, "flags": len(flags)}

    DBOS.workflow(name=STATEMENT_WORKFLOW)(statement)
