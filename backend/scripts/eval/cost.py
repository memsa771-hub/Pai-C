"""Provider-token accounting driven by editable model price data."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class BudgetReached(Exception):
    """A live run must stop and write its partial report."""


def load_prices(path: Path) -> dict[str, dict[str, float]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("model prices must be an object")
    for model, rates in raw.items():
        if (not isinstance(model, str) or not isinstance(rates, dict)
                or any(not isinstance(rates.get(key), (int, float)) or rates[key] < 0
                       for key in ("input", "cached_input", "output"))):
            raise ValueError("each model requires nonnegative input, cached_input and output rates")
        if ("long_context_threshold" in rates and
                (not isinstance(rates["long_context_threshold"], int)
                 or rates["long_context_threshold"] < 1)):
            raise ValueError("long context threshold must be positive")
        if any(not isinstance(rates.get(key), (int, float)) or rates[key] < 1
               for key in ("long_context_input_multiplier", "long_context_output_multiplier")
               if key in rates):
            raise ValueError("long context multipliers must be at least one")
    return raw


def token_record(usage: Any, model: str, phase: str, rates: dict[str, dict[str, float]]) -> dict:
    if model not in rates:
        raise ValueError(f"missing price data for model {model}")
    input_details = getattr(usage, "prompt_tokens_details", None)
    output_details = getattr(usage, "completion_tokens_details", None)
    input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
    cached_tokens = int(getattr(input_details, "cached_tokens", 0) or 0)
    output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
    reasoning_tokens = int(getattr(output_details, "reasoning_tokens", 0) or 0)
    if not 0 <= cached_tokens <= input_tokens:
        raise ValueError("invalid cached token count")
    price = rates[model]
    long_context = bool(price.get("long_context_threshold")
                        and input_tokens > price["long_context_threshold"])
    input_multiplier = price.get("long_context_input_multiplier", 1) if long_context else 1
    output_multiplier = price.get("long_context_output_multiplier", 1) if long_context else 1
    cost = (((input_tokens - cached_tokens) * price["input"]
             + cached_tokens * price["cached_input"]) * input_multiplier
            + output_tokens * price["output"] * output_multiplier) / 1_000_000
    return {"phase": phase, "model": model, "input": input_tokens,
            "cached_input": cached_tokens, "output": output_tokens,
            "reasoning": reasoning_tokens, "cost_usd": round(cost, 8)}


@dataclass
class UsageLedger:
    prices: dict[str, dict[str, float]]
    max_cost_usd: float | None = None
    calls: list[dict] = field(default_factory=list)

    @property
    def spent(self) -> float:
        return sum(item["cost_usd"] for item in self.calls)

    def before_call(self, model: str) -> None:
        if model not in self.prices:
            raise ValueError(f"missing price data for model {model}")
        if self.max_cost_usd is not None and self.spent >= self.max_cost_usd:
            raise BudgetReached("cost budget reached")

    def record(self, usage: Any, model: str, phase: str) -> dict:
        if usage is None:
            raise BudgetReached("provider returned no token usage; cost cannot be enforced")
        row = token_record(usage, model, phase, self.prices)
        self.calls.append(row)
        if self.max_cost_usd is not None and self.spent >= self.max_cost_usd:
            raise BudgetReached("cost budget reached")
        return row
