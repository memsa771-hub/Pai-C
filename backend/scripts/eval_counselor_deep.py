"""Hidden-truth Counselor evaluation on disposable students.

Default mode replays recorded model outputs and forbids provider clients.
Real calls require both --live and --max-cost-usd; this script never runs live
as part of tests or CI.
"""

import argparse
import asyncio
import json
import math
import re
import socket
import time
import uuid
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.config import config
from app.counseling.deep.analysis import analyze_job, enqueue_turn_analysis
from app.counseling.deep.actions import dispatch_action
from app.counseling.deep.notebook import NotebookService
from app.counseling.deep.polish import contains_blocked_script
from app.counseling.deep.turn import run_deep_turn
from app.counseling.deep.turn_input import CounselorTurnInput
from app.inference import client as inference_client
from app.memory.turn_hook import enqueue_turn_extraction
from app.memory.index import NullMemoryIndex
from app.models import BackgroundJob, EventRecord, User
from scripts.counselor_eval_support import StudentSession
from scripts.eval.cost import BudgetReached, UsageLedger, load_prices

ROOT = Path(__file__).resolve().parent
PERSONAS = ROOT.parent / "tests" / "fixtures" / "deep_personas"
PROMPTS = ROOT / "eval" / "prompts"
PRICES = ROOT / "eval" / "model_prices.json"
RESULTS = ROOT / "results"
_phase: ContextVar[str] = ContextVar("deep_eval_phase", default="unknown")


@contextmanager
def phase(name: str):
    token = _phase.set(name)
    try:
        yield
    finally:
        _phase.reset(token)


def load_personas(directory: Path = PERSONAS) -> list[dict]:
    personas = []
    for path in sorted(directory.glob("*.json")):
        item = json.loads(path.read_text(encoding="utf-8"))
        required = ("id", "surface", "hidden_truths", "family", "constraints", "style", "adversarial")
        if not isinstance(item, dict) or any(key not in item for key in required):
            raise ValueError(f"invalid persona fixture: {path.name}")
        if not isinstance(item["hidden_truths"], list) or not isinstance(item["adversarial"], list):
            raise ValueError(f"invalid persona lists: {path.name}")
        personas.append(item)
    if not personas or len({item["id"] for item in personas}) != len(personas):
        raise ValueError("persona fixtures must have unique IDs")
    return personas


def _usage_object(data: dict):
    return SimpleNamespace(
        prompt_tokens=int(data.get("input", 0)), completion_tokens=int(data.get("output", 0)),
        prompt_tokens_details=SimpleNamespace(cached_tokens=int(data.get("cached_input", 0))),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=int(data.get("reasoning", 0))),
    )


class RecordedModels:
    """Feeds the same turn/analysis/extraction functions with recorded outputs."""

    def __init__(self, ledger: UsageLedger):
        self.ledger = ledger
        self.turn: dict = {}

    def _record(self, name: str):
        usage = (self.turn.get("usage") or {}).get(name) or {}
        model = usage.get("model", "gpt-5-mini")
        self.ledger.before_call(model)
        self.ledger.record(_usage_object(usage), model, name)

    async def counselor(self, **_kwargs):
        self._record("counselor")
        return json.dumps(self.turn["counselor"], ensure_ascii=False)

    async def analyst(self, **_kwargs):
        self._record("analyst")
        return json.dumps(self.turn["analyst"], ensure_ascii=False)

    async def sensitive(self, **kwargs):
        self._record("sensitive")
        entries = json.loads(kwargs["messages"][0]["content"])
        flagged = set(self.turn.get("sensitive_flagged_paths") or [])
        return json.dumps({"decisions": [
            {"path": item["path"], "sensitive": item["path"] in flagged}
            for item in entries]}, ensure_ascii=False)

    async def memory(self, **_kwargs):
        self._record("memory_extractor")
        return json.dumps(self.turn.get("memory") or {"candidates": []}, ensure_ascii=False)

    @contextmanager
    def install(self):
        def no_network(*_args, **_kwargs):
            raise AssertionError("offline evaluation attempted a provider client")

        with ExitStack() as stack:
            stack.enter_context(patch("app.memory.index._index", NullMemoryIndex()))
            stack.enter_context(patch.object(socket.socket, "connect", no_network))
            stack.enter_context(patch.object(socket.socket, "connect_ex", no_network))
            stack.enter_context(patch.object(config, "PAI_API_KEY", "recorded-only"))
            stack.enter_context(patch.object(config, "MEMORY_EXTRACTOR_API_KEY", "recorded-only"))
            stack.enter_context(patch("app.inference.client.create_client", no_network))
            stack.enter_context(patch("app.counseling.deep.turn.chat_completion", self.counselor))
            stack.enter_context(patch("app.counseling.deep.analysis.chat_completion", self.analyst))
            stack.enter_context(patch("app.counseling.deep.sensitive.chat_completion", self.sensitive))
            stack.enter_context(patch("app.memory.extractor.chat_completion", self.memory))
            yield


class TrackedLiveClient:
    def __init__(self, api_key, base_url, original, ledger):
        self.real = original(api_key, base_url=base_url).with_options(max_retries=0)
        self.ledger = ledger
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **kwargs):
        model = kwargs["model"]
        limit = int(kwargs.get("max_completion_tokens") or kwargs.get("max_tokens") or 4096)
        kwargs[inference_client._token_limit_kwarg(model)] = limit
        budget_input = list(kwargs["messages"])
        if kwargs.get("tools"):
            budget_input.append({"role": "system", "content": json.dumps(kwargs["tools"])})
        reservation = self.ledger.reserve(model, budget_input, limit)
        try:
            response = await self.real.chat.completions.create(**kwargs)
        except Exception:
            # An ambiguous transport error may still be billable. Retain the
            # reservation, stop, and never issue an automatic retry.
            raise BudgetReached("provider request failed; reservation retained") from None
        self.ledger.settle(getattr(response, "usage", None), model, _phase.get(), reservation)
        return response

    async def close(self):
        await self.real.close()


@contextmanager
def live_tracking(ledger: UsageLedger):
    original = inference_client.create_client
    from app.counseling.deep import sensitive

    real_sensitive_call = sensitive.chat_completion

    async def tagged_sensitive_call(**kwargs):
        with phase("sensitive"):
            return await real_sensitive_call(**kwargs)

    with ExitStack() as stack:
        if config.WEB_SEARCH_PROVIDER:
            from app.tools.web_search import TavilyWebSearchProvider
            prices=json.loads((ROOT / "eval" / "tool_prices.json").read_text())
            original_search=TavilyWebSearchProvider.search
            async def priced_search(provider, query, limit=5):
                cost=prices["tavily"]["basic_search_usd"]
                if ledger.max_cost_usd is not None and ledger.exposure+ledger.reserved_usd+cost*1.1 > ledger.max_cost_usd:
                    raise BudgetReached("search budget reached")
                ledger.calls.append({"phase":"search","model":"tavily","input":0,"cached_input":0,"output":0,"reasoning":0,"cost_usd":cost})
                ledger.checkpoint()
                return await original_search(provider,query,limit)
            if config.WEB_SEARCH_PROVIDER != "tavily":
                raise ValueError("no verified evaluation price for configured search provider")
            stack.enter_context(patch.object(TavilyWebSearchProvider,"search",priced_search))
        stack.enter_context(patch.object(config,"WEB_SEARCH_MAX_RETRIES",0))
        with patch("app.inference.client.create_client",
               lambda api_key, base_url=None: TrackedLiveClient(api_key, base_url, original, ledger)), \
            patch("app.counseling.deep.sensitive.chat_completion", tagged_sensitive_call), \
            patch("app.memory.index._index", NullMemoryIndex()):
            yield


def _eval_context(persona: dict, transcript: list[dict], notebook: dict,
                  inject: str | None = None) -> str:
    persona = {key: value for key, value in persona.items()
               if key not in {"recorded_turns", "recorded_grader"}}
    return "\n".join(f"<{key}>{json.dumps(value, ensure_ascii=False)}</{key}>"
                     for key, value in (("persona", persona), ("transcript", transcript),
                                        ("notebook", notebook), ("inject", inject)))


async def _live_student(persona: dict, transcript: list[dict], model: str,
                        notebook: dict | None = None, inject: str | None = None) -> str:
    from app.inference.client import chat_completion

    prompt = (PROMPTS / "simulated_student.md").read_text(encoding="utf-8")
    with phase("simulated_student"):
        return (await chat_completion(
            api_key=config.PAI_API_KEY, model=model, system_prompt=prompt,
            messages=[{"role": "user", "content": _eval_context(
                persona, transcript, notebook or {}, inject)}],
            base_url=config.PAI_BASE_URL,
        )).strip()


async def _live_grader(persona: dict, transcript: list[dict], notebook: dict, model: str) -> dict:
    from app.inference.client import chat_completion

    prompt = (PROMPTS / "grader.md").read_text(encoding="utf-8")
    with phase("grader"):
        raw = await chat_completion(
            api_key=config.PAI_API_KEY, model=model, system_prompt=prompt,
            messages=[{"role": "user", "content": _eval_context(persona, transcript, notebook)}],
            response_format={"type": "json_object"}, base_url=config.PAI_BASE_URL,
        )
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError("grader did not return an object")
    return result


def _percentile(values: list[int], percentile: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    return round(values[lower] + (values[upper] - values[lower]) * (position - lower), 1)


def _metrics(persona: dict, turns: list[dict], notebook: dict, grader: dict | None) -> dict:
    grader = dict(grader or {})
    if isinstance(grader.get("hidden_truths"), list):
        grader["hidden_truths_captured"] = sum(
            item.get("captured") is True for item in grader["hidden_truths"]
            if isinstance(item, dict))
    claims = notebook.get("claims") or []
    questions = [len(re.findall(r"[?\u061f]", turn["reply"])) for turn in turns]
    mirror_turn = next((turn["turn"] for turn in turns
                        if turn["action"].get("type") == "mirror"), None)
    return {
        **(grader or {}),
        "hidden_truths_total": len(persona["hidden_truths"]),
        "hidden_truths_captured": (grader or {}).get("hidden_truths_captured"),
        "hidden_truth_recall": (round(grader["hidden_truths_captured"] / len(persona["hidden_truths"]), 3)
                                if grader and persona["hidden_truths"]
                                and isinstance(grader.get("hidden_truths_captured"), int) else None),
        "claims_probed_beyond_claimed": sum(item.get("evidence_level") in
                                             {"tried", "sustained", "proven"} for item in claims),
        "claims_total": (grader or {}).get("claims_total"),
        "goal_tested_before_mirror": (grader or {}).get("goal_tested_before_mirror"),
        "mirror_ready_reached": bool(notebook.get("mirror_ready")),
        "mirror_evidence_accurate": ((grader or {}).get("mirror_evidence_accurate")
                                     if mirror_turn is not None else None),
        "reasks_known_facts": (grader or {}).get("reasks_known_facts"),
        "identity_questions": (grader or {}).get("identity_questions"),
        "replies_more_than_one_question": (grader or {}).get("replies_more_than_one_ask"),
        "question_marks_over_one": sum(count > 1 for count in questions),
        "praise_openers": (grader or {}).get("praise_or_filler"),
        "out_of_domain_answers": (grader or {}).get("out_of_domain_answers"),
        "blocked_script_replies": sum(contains_blocked_script(
            turn["reply"], config.PAI_LANGUAGE_BLOCKED_SCRIPTS) for turn in turns),
        "unsourced_world_facts": (grader or {}).get("unsourced_world_facts"),
        "yes_man_replies": (grader or {}).get("yes_man_replies"),
        "turns_to_mirror": mirror_turn,
        "note_question": sum(turn["action"].get("type") == "note_question" for turn in turns),
        "latency_p50_ms": _percentile([turn["counselor_latency_ms"] for turn in turns], 0.5),
        "latency_p95_ms": _percentile([turn["counselor_latency_ms"] for turn in turns], 0.95),
        "pipeline_p50_ms": _percentile([turn["pipeline_ms"] for turn in turns], 0.5),
        "pipeline_p95_ms": _percentile([turn["pipeline_ms"] for turn in turns], 0.95),
    }


async def evaluate_persona(persona: dict, ledger: UsageLedger, *, live: bool,
                           max_turns: int, simulator_model: str = "",
                           grader_model: str = "", end_to_end: bool = False,
                           progress_dir: Path | None = None) -> dict:
    result = {"persona": persona["id"], "turns": [], "status": "complete", "grader": None}
    recorded = RecordedModels(ledger)
    transcript: list[dict] = []
    with StudentSession() as student:
        with student.factory() as db:
            db.get(User, student.user_id).display_name = persona.get("name") or persona["id"]
            db.commit()
        manager = live_tracking(ledger) if live else recorded.install()
        with manager:
            for index in range(1, max_turns + 1):
                fixture = (persona.get("recorded_turns") or [])
                if not live and index > len(fixture):
                    break
                recorded.turn = fixture[index - 1] if not live else {}
                injection = next((item["message"] for item in persona["adversarial"]
                                  if item.get("at_turn") == index), None)
                opener = next((item for item in persona.get("session_openers", [])
                               if item.get("at_turn") == index), None)
                session_id = ((recorded.turn.get("session_id") if not live else None)
                              or (opener or {}).get("session_id")
                              or next((item["session_id"] for item in reversed(
                                  persona.get("session_openers", []))
                                  if item.get("at_turn", 0) < index), "session-1"))
                try:
                    before = len(ledger.calls)
                    if not live:
                        message = recorded.turn["student"]
                    elif index == 1:
                        message = persona["surface"]
                    elif opener:
                        message = opener["student"]
                    else:
                        message = await _live_student(persona, transcript, simulator_model,
                                                      result.get("notebook") or {}, injection)
                    start = time.monotonic()
                    event_id = str(uuid.uuid4())
                    timestamp = student.next_timestamp()
                    with student.factory() as db:
                        db.add(EventRecord(id=event_id, network_id=student.workspace_id,
                                           type="workspace.message.posted",
                                           source=f"human:{student.user_id}",
                                           target="channel/pai-counselor",
                                           payload={"content": message}, timestamp=timestamp))
                        db.commit()
                        turn = CounselorTurnInput("channel/pai-counselor", student.workspace_id,
                                                  message, (), session_id, event_id, timestamp,
                                                  f"human:{student.user_id}",
                                                  persona.get("channel") == "voice")
                        with phase("counselor"):
                            answer = await run_deep_turn(db, turn)
                        action_kind, action_status = await dispatch_action(
                            db, turn, answer.action, answer.context)
                        counselor_latency_ms = round((time.monotonic() - start) * 1000)
                        assistant_id = await student.post_response(
                            db, student.workspace_id, turn.channel, "pai", answer.reply, 0)
                        if live and progress_dir:
                            progress_dir.mkdir(parents=True, exist_ok=True)
                            (progress_dir / f"partial_{persona['id']}.json").write_text(json.dumps({
                                "persona": persona["id"], "turns": result["turns"],
                                "pending_turn": {"student": message, "reply": answer.reply,
                                                 "action": answer.action},
                                "notebook": result.get("notebook"), "calls": ledger.calls},
                                ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                        analysis_id = enqueue_turn_analysis(
                            db, student.workspace_id, event_id, assistant_id)
                        job = db.get(BackgroundJob, analysis_id)
                        with phase("analyst"):
                            await analyze_job(job, db)
                        job.status = "succeeded"
                        db.commit()
                        enqueue_turn_extraction(
                            db, student.workspace_id, turn.channel, event_id,
                            assistant_id, "pai")
                    with phase("memory_extractor"):
                        await student.extract_and_reconcile()
                    with student.factory() as db:
                        notebook = NotebookService(db).get(student.workspace_id).notebook.model_dump(mode="json")
                    transcript.extend([{"role": "student", "content": message},
                                       {"role": "counselor", "content": answer.reply}])
                    calls = ledger.calls[before:]
                    result["turns"].append({
                        "turn": index, "student": message, "reply": answer.reply,
                        "action": {**answer.action, "type": action_kind},
                        "action_status": action_status, "counselor_latency_ms": counselor_latency_ms,
                        "pipeline_ms": round((time.monotonic() - start) * 1000),
                        "model_calls": len(calls), "usage": calls,
                        "cost_usd": round(sum(call["cost_usd"] for call in calls), 8),
                    })
                    result["notebook"] = notebook
                    if answer.action.get("type") == "mirror" and (not end_to_end or action_status == "requested"):
                        if end_to_end and action_status == "requested":
                            result["completion"] = await complete_mirror_pipeline(student)
                            transcript.extend(result["completion"].get("transcript") or [])
                        break
                except BudgetReached as exc:
                    result["status"] = "budget_reached"
                    result["stop_reason"] = str(exc)
                    break
                except Exception as exc:
                    result["status"]="failed"
                    result["stop_reason"]=type(exc).__name__
                    break
            if result["status"] != "budget_reached" and live:
                try:
                    result["grader"] = await _live_grader(
                        persona, transcript, result.get("notebook") or {}, grader_model)
                except BudgetReached as exc:
                    result["status"] = "budget_reached"
                    result["stop_reason"] = str(exc)
                except (TypeError, ValueError) as exc:
                    result["status"] = "grader_failed"
                    result["stop_reason"] = type(exc).__name__
            elif not live:
                result["grader"] = persona.get("recorded_grader")
    result["metrics"] = _metrics(persona, result["turns"], result.get("notebook") or {}, result["grader"])
    return result



async def complete_mirror_pipeline(student):
    """Exercise existing durable jobs, confirmation, gateway and Operator.

    Confirmation belongs only to the synthetic evaluation student. No existing
    database is opened, and external write actions remain disabled by EvalWorkspaceApi.
    """
    from sqlalchemy import select
    from app.counseling.deep.mirror import mirror_job, enqueue_confirmed_research, confirmed_research_job, JOB_MIRROR
    from app.journey import JourneyService
    from app.models import Roadmap
    from app.services import operator
    with student.factory() as db:
        job=db.scalar(select(BackgroundJob).where(BackgroundJob.workspace_id==student.workspace_id,
            BackgroundJob.job_type==JOB_MIRROR,BackgroundJob.status=='pending'))
        if job is None: return {'status':'mirror_not_queued'}
        with phase('mirror'), patch('app.counseling.deep.mirror._post_response',student.post_response):
            outcome=await mirror_job(job,db)
        job.status='succeeded'; db.commit()
        journey=JourneyService(db).ensure_counselor(student.workspace_id)
        draft=journey.counselor_summary_draft or {}
        result={'status':outcome['status'],'mirror':draft.get('mirror'),'transcript':[]}
        if draft.get('status')!='awaiting_confirmation': return result
        result['transcript'].append({'role':'mirror','content':draft.get('mirror')})
        journey=JourneyService(db).queue_counselor_research(student.workspace_id,journey.id,str(uuid.uuid4()),
            actor='human:evaluation_confirmation',expected_version=draft['version'])
        research_id=enqueue_confirmed_research(db,student.workspace_id,journey);db.commit()
        with phase('light_research'):
            await confirmed_research_job(db.get(BackgroundJob,research_id),db)
            tasks=list(operator._running_tasks)
            if tasks: await asyncio.gather(*tasks)
        db.expire_all()
        rows=db.scalars(select(Roadmap).where(Roadmap.workspace_id==student.workspace_id)).all()
        result['roadmaps']=[{'lane':row.lane,'title':row.title,'status':row.generation_status,
            'route':row.route,'sources':row.sources,'gaps':row.gaps,'steps':row.steps} for row in rows]
        result['ready_ratio']=sum(row.generation_status=='ready' for row in rows)/len(rows) if rows else 0
        result['status']='published' if rows else 'no_roadmaps'
        result['transcript'].append({'role':'roadmaps','content':result['roadmaps']})
        return result


def write_report(report: dict, directory: Path) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"counselor_deep_{datetime.now(timezone.utc):%Y%m%d}"
    json_path = directory / f"{stem}.json"
    md_path = directory / f"{stem}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Deep Counselor evaluation", "",
             f"Mode: {report['mode']} | Status: {report['status']} | Cost: ${report['cost_usd']:.6f}", "",
             "| Persona | Turns | Mirror turn | Mirror ready | Goal tested | Mirror accurate | Hidden recall | Claims probed | Re-asks | Identity asks | Multi-asks | Praise | Domain | Blocked script | Unsourced facts | Yes-man | Counselor p50/p95 ms | Pipeline p50/p95 ms | Cost USD |",
             "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |"]
    for item in report["personas"]:
        metric = item["metrics"]
        value = lambda key: metric.get(key) if metric.get(key) is not None else "ungraded"
        lines.append("| " + " | ".join(map(str, [
            item["persona"], len(item["turns"]), value("turns_to_mirror"),
            value("mirror_ready_reached"), value("goal_tested_before_mirror"),
            value("mirror_evidence_accurate"),
            value("hidden_truth_recall"), f"{value('claims_probed_beyond_claimed')}/{value('claims_total')}",
            value("reasks_known_facts"), value("identity_questions"),
            value("replies_more_than_one_question"), value("praise_openers"),
            value("out_of_domain_answers"), value("blocked_script_replies"),
            value("unsourced_world_facts"), value("yes_man_replies"),
            f"{value('latency_p50_ms')} / {value('latency_p95_ms')}",
            f"{value('pipeline_p50_ms')} / {value('pipeline_p95_ms')}",
            f"{item['total_cost_usd']:.6f}"])) + " |")
    lines.extend(["", "Ungraded values require a recorded or live grader decision; they are not assumed to be zero.",
                  ""])
    for item in report["personas"]:
        lines.extend([f"## {item['persona']}", "", f"Status: {item['status']}", "",
                      "| Turn | Student | Counselor | Action | Counselor ms | Pipeline ms | Model calls | Cost USD |",
                      "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |"])
        for turn in item["turns"]:
            cells = [turn["turn"], turn["student"], turn["reply"],
                     turn["action"].get("type", "none"), turn["counselor_latency_ms"],
                     turn["pipeline_ms"],
                     turn["model_calls"], f"{turn['cost_usd']:.6f}"]
            lines.append("| " + " | ".join(str(cell).replace("|", "\\|").replace("\n", " ")
                                           for cell in cells) + " |")
        lines.extend(["", "| Phase | Calls | Input | Cached input | Output | Reasoning | Cost USD |",
                      "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"])
        for name, usage in item["usage_by_phase"].items():
            lines.append(f"| {name} | {usage['calls']} | {usage['input']} | "
                         f"{usage['cached_input']} | {usage['output']} | {usage['reasoning']} | "
                         f"{usage['cost_usd']:.6f} |")
        lines.append("")
        lines.extend(["### End-to-end completion", "", "```json", json.dumps(item.get("completion"), ensure_ascii=False, indent=2), "```", ""])
        lines.extend(["### Grader decisions and evidence", "", "```json",
                      json.dumps(item.get("grader"), ensure_ascii=False, indent=2), "```", ""])
    lines.extend(["The JSON report includes every per-call token record and final notebook.", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path, json_path


async def run_evaluation(*, live: bool = False, max_cost_usd: float | None = None,
                         max_turns: int = 40, persona_ids: set[str] | None = None,
                         fixture_dir: Path = PERSONAS, price_file: Path = PRICES,
                         result_dir: Path = RESULTS, simulator_model: str = "",
                         grader_model: str = "", end_to_end: bool = False) -> dict:
    if live and (max_cost_usd is None or max_cost_usd <= 0):
        raise ValueError("--live requires a positive --max-cost-usd")
    if max_turns < 1:
        raise ValueError("--max-turns must be positive")
    if live and not config.PAI_API_KEY:
        raise ValueError("--live requires the configured backend model key")
    personas = [item for item in load_personas(fixture_dir)
                if persona_ids is None or item["id"] in persona_ids]
    if not personas:
        raise ValueError("no selected persona fixtures")
    ledger = UsageLedger(load_prices(price_file), max_cost_usd)
    if live:
        ledger.checkpoint_path = result_dir / "live_usage_ledger.json"
    if live:
        for model in {config.PAI_COUNSELOR_MODEL, config.PAI_ANALYST_MODEL,
                      config.PAI_SENSITIVE_CHECK_MODEL,
                      *({config.PAI_MIRROR_MODEL, config.PAI_ROADMAP_MODEL, config.PAI_OPERATOR_MODEL or config.PAI_MODEL} if end_to_end else set()),
                      config.MEMORY_EXTRACTOR_MODEL or config.PAI_MODEL,
                      simulator_model or config.PAI_MODEL,
                      grader_model or config.PAI_COUNSELOR_MODEL}:
            ledger.before_call(model)
            if ledger.prices[model].get("verify_before_live"):
                raise ValueError(f"price verification required before live: {model}")
    result = {"mode": "live" if live else "offline", "status": "complete", "personas": [],
              "cost_usd": 0.0, "all_calls": []}
    for persona in personas:
        persona_start = len(ledger.calls)
        item = await evaluate_persona(
            persona, ledger, live=live, max_turns=max_turns,
            simulator_model=simulator_model or config.PAI_MODEL,
            grader_model=grader_model or config.PAI_COUNSELOR_MODEL, end_to_end=end_to_end,
            progress_dir=result_dir if live else None)
        persona_calls = ledger.calls[persona_start:]
        item["total_cost_usd"] = round(sum(call["cost_usd"] for call in persona_calls), 8)
        item["usage_by_phase"] = {
            name: {"calls": sum(call["phase"] == name for call in persona_calls),
                   **{field: sum(call[field] for call in persona_calls if call["phase"] == name)
                      for field in ("input", "cached_input", "output", "reasoning", "cost_usd")}}
            for name in sorted({call["phase"] for call in persona_calls})
        }
        result["personas"].append(item)
        result["cost_usd"] = round(ledger.spent, 8)
        result["all_calls"] = ledger.calls
        if item["status"] == "budget_reached":
            result["status"] = "budget_reached"
            break
    paths = write_report(result, result_dir)
    result["paths"] = [str(path) for path in paths]
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="Replay recorded fixtures (default)")
    mode.add_argument("--live", action="store_true", help="Allow real model calls")
    parser.add_argument("--max-cost-usd", type=float)
    parser.add_argument("--end-to-end", action="store_true", help="Generate Mirror, confirm and await real research/publication")
    parser.add_argument("--max-turns", type=int, default=40)
    parser.add_argument("--persona", action="append", dest="personas")
    parser.add_argument("--simulator-model", default="")
    parser.add_argument("--grader-model", default="")
    parser.add_argument("--result-dir", type=Path, default=RESULTS)
    args = parser.parse_args()
    if args.live and (args.max_cost_usd is None or args.max_cost_usd <= 0):
        parser.error("--live requires --max-cost-usd greater than zero")
    result = asyncio.run(run_evaluation(
        live=args.live, max_cost_usd=args.max_cost_usd, max_turns=args.max_turns,
        persona_ids=set(args.personas) if args.personas else None,
        result_dir=args.result_dir, simulator_model=args.simulator_model,
        grader_model=args.grader_model, end_to_end=args.end_to_end))
    print(json.dumps({"status": result["status"], "personas": len(result["personas"]),
                      "cost_usd": result["cost_usd"], "paths": result["paths"]}))


if __name__ == "__main__":
    main()
