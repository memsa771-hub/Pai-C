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
    reserved_usd: float = 0.0
    checkpoint_path: Path | None = None

    def checkpoint(self) -> None:
        if self.checkpoint_path:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.checkpoint_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"calls": self.calls, "estimated_usd": self.spent,
                "exposure_usd": self.exposure, "reserved_usd": self.reserved_usd,
                "cap_usd": self.max_cost_usd}, indent=2) + "\n")
            temporary.replace(self.checkpoint_path)

    @property
    def spent(self) -> float:
        return sum(item["cost_usd"] for item in self.calls)

    @property
    def exposure(self) -> float:
        """Conservative billable upper estimate, including cache writes/region."""
        return sum(item["cost_usd"] * 1.1 * max(1, self.prices.get(item["model"], {}).get("cache_write", 0)
            / (self.prices.get(item["model"], {}).get("input", 0) or 1)) for item in self.calls)

    def before_call(self, model: str) -> None:
        if model not in self.prices:
            raise ValueError(f"missing price data for model {model}")
        if self.max_cost_usd is not None and self.exposure + self.reserved_usd >= self.max_cost_usd:
            raise BudgetReached("cost budget reached")

    def reserve(self, model: str, messages: list[dict], output_limit: int) -> float:
        """Reserve worst-case uncached cost BEFORE a request, including reasoning.

        UTF-8 byte count is a conservative upper bound for text tokenization;
        allow additional framing overhead per message. Eval accepts text only.
        The output limit is sent to the provider, and SDK retries are disabled.
        """
        self.before_call(model)
        price = self.prices[model]
        if price.get("verify_before_live"):
            raise ValueError(f"price verification required before live: {model}")
        if output_limit < 1 or any(item.get("content") is not None and not isinstance(item.get("content"), str) for item in messages):
            raise ValueError("budgeted evaluation requires text messages and a positive output limit")
        input_bound = sum(len(json.dumps(item, ensure_ascii=False).encode("utf-8")) + 128 for item in messages) + 1024
        long = bool(price.get("long_context_threshold") and input_bound > price["long_context_threshold"])
        bound = 1.1 * (input_bound * max(price["input"], price.get("cache_write", price["input"])) * (price.get("long_context_input_multiplier", 1) if long else 1)
                 + output_limit * price["output"] * (price.get("long_context_output_multiplier", 1) if long else 1)) / 1_000_000
        if self.max_cost_usd is not None and self.exposure + self.reserved_usd + bound > self.max_cost_usd:
            raise BudgetReached("remaining budget cannot cover the next bounded request")
        self.reserved_usd += bound
        self.checkpoint()
        return bound

    def settle(self, usage: Any, model: str, phase: str, reservation: float) -> dict:
        if usage is None:
            raise BudgetReached("missing usage; reservation retained and run stopped")
        self.reserved_usd = max(0, self.reserved_usd - reservation)
        return self.record(usage, model, phase)

    def record(self, usage: Any, model: str, phase: str) -> dict:
        if usage is None:
            raise BudgetReached("provider returned no token usage; cost cannot be enforced")
        row = token_record(usage, model, phase, self.prices)
        self.calls.append(row)
        self.checkpoint()
        if self.max_cost_usd is not None and self.spent >= self.max_cost_usd:
            raise BudgetReached("cost budget reached")
        return row
