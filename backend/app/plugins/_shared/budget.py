"""Per-research-run limits propagated through nested capability tool calls."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
import time

# Budget keys older than this are dropped when a counter is written, so the
# workspace settings never grow (the allowance itself is one UTC day).
KEEP_DAYS = 7
_DATED = re.compile(r":(\d{4}-\d{2}-\d{2})$")
# Whole-Vault-version keys written briefly before the daily key (44bd9e4).
_LEGACY_DIGEST = re.compile(r"^[0-9a-f]{16}$")


def daily_key(scope: str, now: datetime | None = None) -> str:
    """One allowance per workspace, scope and UTC calendar day."""
    return f"{scope}:{(now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()}"


def _pruned(counters: dict, today: date) -> dict:
    """Drop dated keys older than KEEP_DAYS and the bare numbers the old
    per-Mirror-version budget left (and the 16-hex Vault-version keys); other keys (belief-check periods) stay."""
    def keep(key: str) -> bool:
        if key.isdigit() or _LEGACY_DIGEST.match(key):
            return False
        match = _DATED.search(key)
        return not match or date.fromisoformat(match.group(1)) >= today - timedelta(days=KEEP_DAYS)
    return {key: value for key, value in counters.items() if keep(key)}


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
    budget_key: str | None = None
    scope: str = "path_research"
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
                # Counters belong to a key (a UTC day for path research, a
                # period for belief checks), not a lifetime. Keeping the keys
                # prevents an old job from resetting a new job's allowance.
                counters = _pruned(dict(settings.get("counselor_research_budgets") or {}),
                                   datetime.now(timezone.utc).date())
                key = str(self.budget_key)
                used = int(counters.get(key, 0))
                limit = config.PAI_RESEARCH_MAX_CALLS_PER_STUDENT
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
                     budget_key=None, scope="path_research", refresh_key=None):
    budget = ResearchBudget(max(0, queries), max(0, fetches),
                            time.monotonic() + max(1, seconds), workspace_id=workspace_id,
                            budget_key=budget_key, scope=scope, refresh_key=refresh_key)
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
