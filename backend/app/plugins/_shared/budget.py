"""Per-research-run limits propagated through nested capability tool calls."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import time


@dataclass
class ResearchBudget:
    queries_left: int
    fetches_left: int
    deadline: float
    queries_used: int = 0
    fetches_used: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model_calls: int = 0
    workspace_id: str | None = None
    mirror_version: int | None = None
    scope: str = "roadmap_light"
    refresh_key: str | None = None
    exhausted: bool = False

    def spend(self, tool_name: str) -> str | None:
        if time.monotonic() >= self.deadline:
            return "research_time_budget_exceeded"
        if tool_name in {"web.search", "web.institution_registry"} and self.queries_left <= 0:
            return "research_query_budget_exceeded"
        if tool_name == "web.fetch" and self.fetches_left <= 0:
            return "research_fetch_budget_exceeded"
        if tool_name in {"web.search", "web.fetch", "web.institution_registry", "model"} and self.workspace_id:
            from app.config import config
            from app.database import new_session
            from app.models import Workspace
            from sqlalchemy import select
            with new_session() as db:
                workspace = db.scalar(select(Workspace).where(Workspace.id == self.workspace_id,
                    Workspace.status == "active").with_for_update())
                if workspace is None:
                    self.exhausted = True
                    return "research_student_budget_exceeded"
                settings = dict(workspace.settings or {})
                # Counters belong to a confirmed Mirror version, not a lifetime.
                # Keeping version keys prevents an old job from resetting a new
                # job's allowance. Refresh attempts have a separate allowance.
                counters = dict(settings.get("counselor_research_budgets") or {})
                key = str(self.mirror_version)
                if self.scope == "stale_refresh":
                    key += ":refresh"
                used = int(counters.get(key, 0))
                limit = (config.PAI_RESEARCH_REFRESH_MAX_CALLS if self.scope == "stale_refresh"
                         else config.PAI_RESEARCH_MAX_CALLS_PER_STUDENT)
                if used >= max(0, limit):
                    self.exhausted = True
                    return "research_student_budget_exceeded"
                counters[key] = used + 1
                settings["counselor_research_budgets"] = counters
                workspace.settings = settings
                db.commit()
        if tool_name in {"web.search", "web.institution_registry"}:
            if self.queries_left <= 0:
                return "research_query_budget_exceeded"
            self.queries_left -= 1
            self.queries_used += 1
        elif tool_name == "web.fetch":
            if self.fetches_left <= 0:
                return "research_fetch_budget_exceeded"
            self.fetches_left -= 1
            self.fetches_used += 1
        return None

    def usage(self) -> dict:
        """Count calls and tokens without guessing a provider-specific price."""
        return {"queries": self.queries_used, "fetches": self.fetches_used,
                "model_calls": self.model_calls, "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens}


_budget: ContextVar[ResearchBudget | None] = ContextVar("research_budget", default=None)


@contextmanager
def bounded_research(*, queries: int, fetches: int, seconds: float, workspace_id=None,
                     mirror_version=None, scope="roadmap_light", refresh_key=None):
    budget = ResearchBudget(max(0, queries), max(0, fetches),
                            time.monotonic() + max(1, seconds), workspace_id=workspace_id,
                            mirror_version=mirror_version, scope=scope, refresh_key=refresh_key)
    token = _budget.set(budget)
    try:
        yield budget
    finally:
        _budget.reset(token)


def spend(tool_name: str) -> str | None:
    budget = _budget.get()
    return budget.spend(tool_name) if budget else None


def record_model_usage(usage) -> None:
    budget = _budget.get()
    if budget is None:
        return
    budget.model_calls += 1
    budget.input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
    budget.output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)
