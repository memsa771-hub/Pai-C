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

    def spend(self, tool_name: str) -> str | None:
        if time.monotonic() >= self.deadline:
            return "research_time_budget_exceeded"
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
def bounded_research(*, queries: int, fetches: int, seconds: float):
    budget = ResearchBudget(max(0, queries), max(0, fetches),
                            time.monotonic() + max(1, seconds))
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
