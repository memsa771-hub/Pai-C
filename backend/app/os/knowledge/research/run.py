"""The research workflow `os.research` and the `knowledge.research` module's kernel-side enqueue (Slice 2 spec
§4.6, S2-D3, S2-D7, S2-D9, S2-D10).

One run per (programme, intake year, day), shared by every confirm_fact task waiting on that programme. The
worker's enqueue loop starts it through DBOSClient (R2-P1), never a step. Every side effect is a DBOS step:
the budget check and run row, each page fetch, each agent-run row, the judge and the store. The readings run
at workflow level, so each model request is its own step (DBOSDurability). Step retries are the only retries
(invariant 7), and every write is idempotent (invariant 8): the run row is keyed by workflow ID, agent runs by
(run, reading), facts by their key, and an event is written only when the stored value or status changes.
"""

from collections.abc import Callable, Mapping
from dataclasses import asdict
from datetime import date, datetime, timezone

from dbos import DBOS, DBOSClient, EnqueueOptions
from sqlalchemy import Engine, insert, select, update

from app.os import models
from app.os.agents.spec import AgentSpec
from app.os.compiler import CONFIRM_TYPE, CompileError
from app.os.knowledge.changes import after_fact_change
from app.os.knowledge.port import Fact
from app.os.knowledge.profile import ResearchProfile, reading_model
from app.os.knowledge.programmes import ProgrammeStore
from app.os.knowledge.research.links import rank_links
from app.os.knowledge.research.pages import PageGateway
from app.os.knowledge.research.readings import AgentRuns, cost, run_reading, user_prompt
from app.os.knowledge.research.trust import judge
from app.os.knowledge.store import SqlKnowledge
from app.os.settings import OsSettings

RESEARCH_WORKFLOW = "os.research"
R = models.research_runs
T = models.tasks
P = models.plans
E = models.events


def research_workflow_id(tenant_id: str, programme_ref: str, intake_year: int, day: date | str) -> str:
    day = day.isoformat() if isinstance(day, date) else day
    return f"research:{tenant_id}:{programme_ref}:{intake_year}:{day}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- kernel side: start the day's runs -----------------------------------------------------------------------


def enqueue_one(engine: Engine, client: DBOSClient, tenant_id: str, programme_ref: str, intake_year: int,
                today: date) -> tuple[str, bool]:
    """Starts today's run for one programme unless it already ran: (workflow ID, whether it was sent).
    Enqueueing the same workflow ID again returns the existing workflow, so a race is harmless."""
    from app.os.runner.workflow import APP_VERSION, QUEUE_NAME  # imported here: the runner imports knowledge

    wid = research_workflow_id(tenant_id, programme_ref, intake_year, today)
    with engine.connect() as conn:
        if conn.execute(select(R.c.id).where(R.c.tenant_id == tenant_id, R.c.workflow_id == wid)).first():
            return wid, False
    options: EnqueueOptions = {"queue_name": QUEUE_NAME, "workflow_name": RESEARCH_WORKFLOW, "workflow_id": wid,
                               "app_version": APP_VERSION}
    client.enqueue(options, programme_ref, intake_year, today.isoformat())
    return wid, True


def enqueue_research(engine: Engine, client: DBOSClient, tenant_id: str, today: date) -> int:
    """Starts one run per (programme, intake) that has confirm_fact tasks waiting for research and no run
    today. Returns how many were sent."""
    year = P.c.contract["target_intake"]["year"].as_integer()
    with engine.connect() as conn:
        wanted = conn.execute(select(T.c.programme_ref, year).distinct().join(P, P.c.id == T.c.plan_id).where(
            T.c.tenant_id == tenant_id, T.c.task_type == CONFIRM_TYPE, T.c.state == "waiting_review",
            T.c.result["waiting_for"].as_string() == "research", T.c.programme_ref.is_not(None),
        ).order_by(T.c.programme_ref)).all()
    return sum(enqueue_one(engine, client, tenant_id, ref, intake_year, today)[1] for ref, intake_year in wanted)


# --- store (spec §4.6 steps 4-6) -----------------------------------------------------------------------------


def fact_value(spec, value, intake_year: int):
    """The value as the compiler and the store hold it: a `month_day` becomes a date in the intake year (the
    compiler anchors on {"date": "YYYY-MM-DD"}), and a `name_set` becomes its list of names (an empty list is
    "no test"; the playbook's `present` condition reads it). Other types keep the profile's shape."""
    if value is None:
        return None
    if spec.type == "month_day":
        return {"date": f"{intake_year}-{value}"}
    if spec.type == "name_set":
        return list(value["any_of"])
    return value


def _event(conn, kind: str, payload: dict) -> None:
    conn.execute(insert(E).values(tenant_id=payload["tenant_id"], type=kind, payload=payload))


def store_research(engine: Engine, service, kernel, run_id: int, programme_ref: str, intake_year: int,
                   profile: ResearchProfile, verdicts: Mapping[str, dict], now: datetime) -> dict:
    """Upserts each researched field. Never downgrades a confirmed fact: a different value from research is a
    conflict note and a `fact_conflict` event, and the value stays. Changed facts write `fact_changed` and
    revise the plans that use them; confirmed facts also complete their waiting confirm tasks."""
    tenant = kernel.tenant_id
    knowledge = SqlKnowledge(engine, tenant)
    counts = {"confirmed": 0, "unconfirmed": 0, "conflicts": 0, "skipped": 0}
    existing = knowledge.programme_facts([programme_ref], [f.name for f in profile.fields], intake_year)
    base = {"tenant_id": tenant, "scope": "programme", "ref": programme_ref, "intake_year": intake_year,
            "research_run_id": run_id}
    for spec in profile.fields:
        v = verdicts.get(spec.name)
        if not v or v["status"] == "not_found":
            continue  # stays as it is (a missing fact stays fact_missing for an admin, spec §4.6 step 5)
        counts[v["status"]] += 1
        new_value = fact_value(spec, v["value"], intake_year)
        old = existing.get((programme_ref, spec.name))
        if old is not None and old.confirmed:
            if new_value != old.value:
                note = f'research found {new_value!r} ({v["status"]}): "{v["quote"] or ""}" ({v["url"] or "no page"})'
                if old.conflict_note != note:
                    knowledge.annotate(old.id, conflict_note=note)
                    with engine.begin() as conn:
                        _event(conn, "fact_conflict", {**base, "field": spec.name, "kept": old.value,
                                                       "found": new_value, "found_status": v["status"],
                                                       "evidence": v["evidence"]})
                counts["conflicts"] += 1
            elif v["status"] == "confirmed":
                knowledge.annotate(old.id, conflict_note=None, checked_at=now)  # the same value, checked again
            continue
        try:
            service.check_fact_value(spec.name, new_value)
            fact = Fact(value=new_value, quote=v["quote"] or "", url=v["url"] or "", checked_at=now,
                        intake_year=intake_year, status=v["status"], conflict_note=v["conflict_note"])
        except (CompileError, ValueError):
            counts["skipped"] += 1  # e.g. a day that is not a date; the evidence is in the run's agent rows
            continue
        changed = old is None or old.value != new_value or old.status != v["status"]
        fact_id = knowledge.upsert("programme", programme_ref, spec.name, fact, source="research",
                                   research_run_id=run_id, evidence=v["evidence"])
        if changed:
            with engine.begin() as conn:
                _event(conn, "fact_changed", {
                    **base, "field": spec.name, "fact_id": fact_id,
                    "old": None if old is None else {"value": old.value, "status": old.status},
                    "new": {"value": new_value, "status": v["status"]}})
        if changed or v["status"] == "confirmed":
            after_fact_change(service, kernel, "programme", programme_ref, spec.name, fact_id, v["status"],
                              intake_year, complete=v["status"] == "confirmed")
    return counts


# --- the workflow --------------------------------------------------------------------------------------------


def _needs_third(verdicts: Mapping[str, dict]) -> bool:
    """Some field has exactly one valid reading (S2-D7)."""
    return any(sum(1 for e in v.get("evidence", []) if not e["reasons"]) == 1 for v in verdicts.values())


def register_research(engine: Engine, settings: OsSettings, kernel, service, gateway: PageGateway,
                      readers: Mapping[str, Mapping[str, object]], spec: AgentSpec,
                      profiles: Mapping[str, ResearchProfile], clock: Callable[[], datetime] = _utcnow) -> None:
    """Registers os.research and its steps. Must run before DBOS.launch(), with readers built once per process.

    `readers` maps a route key to its readers A, B and C (readings.build_readers)."""
    from app.os.runner.workflow import STEP_CONFIG  # imported here: the runner imports knowledge

    tenant = kernel.tenant_id
    runs, programmes = AgentRuns(engine, tenant), ProgrammeStore(engine, tenant)

    def start(programme_ref: str, intake_year: int, wid: str) -> dict:
        """The run row, or `skipped_budget` (with a budget_exceeded event) when the month's cap is spent."""
        with engine.begin() as conn:
            row = conn.execute(select(R.c.id, R.c.status).where(R.c.tenant_id == tenant, R.c.workflow_id == wid)).first()
            if row is not None:
                return {"run_id": row.id, "status": row.status}
            spent = runs.month_spend(clock())
            status = "skipped_budget" if spent >= settings.research_monthly_usd else "running"
            run_id = conn.execute(insert(R).values(tenant_id=tenant, programme_ref=programme_ref,
                                                   intake_year=intake_year, workflow_id=wid, status=status,
                                                   ended_at=clock() if status != "running" else None)
                                  .returning(R.c.id)).scalar_one()
            if status == "skipped_budget":
                _event(conn, "budget_exceeded", {"tenant_id": tenant, "programme_ref": programme_ref,
                                                 "intake_year": intake_year, "spent_usd": spent,
                                                 "cap_usd": settings.research_monthly_usd, "research_run_id": run_id})
        return {"run_id": run_id, "status": status}

    def load_programme(programme_ref: str):
        return programmes.get(programme_ref)

    def fetch(url: str, own: list, shared: list):
        return gateway.fetch(url, own, shared)

    def fetch_failed(url: str, reason: str):
        return gateway.record_failure(url, reason)

    def record(run_id: int, reading: str, model: str, usage: dict, cost_usd: float, error: str | None) -> None:
        from pydantic_ai.usage import RunUsage

        runs.record(run_id, reading, spec=spec, model=model, usage=RunUsage(**usage), cost_usd=cost_usd, error=error)

    def judge_all(route_key: str, programme, intake_year: int, readings: dict, pages: list) -> dict:
        profile = profiles[route_key]
        model = reading_model(profile)
        parsed = {n: model.model_validate(r) for n, r in readings.items() if r is not None}
        return {f.name: asdict(judge(f, {n: getattr(r, f.name) for n, r in parsed.items()}, pages, programme,
                                     profile, intake_year))
                for f in profile.fields}

    def store(run_id: int, programme_ref: str, intake_year: int, route_key: str, verdicts: dict) -> dict:
        return store_research(engine, service, kernel, run_id, programme_ref, intake_year, profiles[route_key],
                              verdicts, clock())

    def finish(run_id: int, status: str, pages: int, counts: dict, cost_usd: float) -> None:
        with engine.begin() as conn:
            conn.execute(update(R).where(R.c.id == run_id).values(
                status=status, ended_at=clock(), pages=pages, confirmed=counts.get("confirmed", 0),
                unconfirmed=counts.get("unconfirmed", 0), cost_usd=cost_usd))

    step = lambda name, fn: DBOS.step(name=f"os.research.{name}", **STEP_CONFIG)(fn)  # noqa: E731
    start_step, programme_step = step("start", start), step("programme", load_programme)
    fetch_step, failed_step, record_step = step("fetch", fetch), step("fetch_failed", fetch_failed), step("record", record)
    judge_step, store_step, finish_step = step("judge", judge_all), step("store", store), step("finish", finish)

    def get_page(url: str, own: list, shared: list):
        try:
            return fetch_step(url, own, shared)
        except Exception as e:  # noqa: BLE001  (the step's retries are used up: recorded as a blocked page)
            return failed_step(url, type(e).__name__)

    def read(name: str, agents, run_id: int, prompt: str) -> tuple[dict | None, float]:
        result = run_reading(agents[name], spec, prompt)
        usage = {"input_tokens": result.usage.input_tokens or 0, "cache_read_tokens": result.usage.cache_read_tokens or 0,
                 "output_tokens": result.usage.output_tokens or 0, "requests": result.usage.requests or 0}
        c = cost(result.usage, settings, spec.tier)
        record_step(run_id, name, agents[name].model.model_name, usage, c, result.error)
        return (None if result.reading is None else result.reading.model_dump()), c

    def research(programme_ref: str, intake_year: int, day: str) -> dict:
        begun = start_step(programme_ref, intake_year, DBOS.workflow_id)
        run_id = begun["run_id"]
        if begun["status"] != "running":
            return begun
        programme = programme_step(programme_ref)
        if programme is None or programme.route_key not in profiles or programme.route_key not in readers:
            finish_step(run_id, "failed", 0, {}, 0.0)
            return {"run_id": run_id, "status": "failed"}
        profile, agents = profiles[programme.route_key], readers[programme.route_key]
        own, shared = list(programme.official_domains), list(profile.official_sources)
        pages = [get_page(u, own, shared) for u in programme.start_urls]
        seen = set(programme.start_urls) | {p.final_url for p in pages if p.final_url}
        pages += [get_page(u, own, shared)
                  for u in rank_links([p for p in pages if p.ok], own, profile.link_keywords, seen)]
        prompt = user_prompt(programme, pages)
        readings, spent = {}, 0.0
        for name in ("A", "B"):
            readings[name], c = read(name, agents, run_id, prompt)
            spent += c
        if all(r is None for r in readings.values()):
            finish_step(run_id, "failed", sum(p.ok for p in pages), {}, spent)  # model down: tasks wait for an admin
            return {"run_id": run_id, "status": "failed"}
        verdicts = judge_step(programme.route_key, programme, intake_year, readings, pages)
        if (_needs_third(verdicts) and len(readings) < spec.limits.max_readings
                and spent < spec.limits.spend_usd_per_programme):
            readings["C"], c = read("C", agents, run_id, prompt)
            spent += c
            verdicts = judge_step(programme.route_key, programme, intake_year, readings, pages)
        counts = store_step(run_id, programme_ref, intake_year, programme.route_key, verdicts)
        finish_step(run_id, "done", sum(p.ok for p in pages), counts, spent)
        return {"run_id": run_id, "status": "done", **counts}

    DBOS.workflow(name=RESEARCH_WORKFLOW)(research)
