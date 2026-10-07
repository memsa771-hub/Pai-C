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

    def spend(self, tool_name: str) -> str | None:
        if time.monotonic() >= self.deadline:
            return "research_time_budget_exceeded"
        if tool_name in {"web.search", "web.institution_registry"}:
            if self.queries_left <= 0:
                return "research_query_budget_exceeded"
            self.queries_left -= 1
        elif tool_name == "web.fetch":
            if self.fetches_left <= 0:
                return "research_fetch_budget_exceeded"
            self.fetches_left -= 1
        return None


_budget: ContextVar[ResearchBudget | None] = ContextVar("research_budget", default=None)


@contextmanager
def bounded_research(*, queries: int, fetches: int, seconds: float):
    token = _budget.set(ResearchBudget(max(0, queries), max(0, fetches),
                                       time.monotonic() + max(1, seconds)))
    try:
        yield
    finally:
        _budget.reset(token)


def spend(tool_name: str) -> str | None:
    budget = _budget.get()
    return budget.spend(tool_name) if budget else None
