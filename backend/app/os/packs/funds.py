"""The funds calculator (Slice 6b spec S6b-D4), a pure function: what the student must show for the visa.

Required = the route's funds fact x months / 12, less what other proof (a scholarship, a sponsor) covers, never below
0. The fact, the months and the currency label come from the route's visa YAML; Python holds no amount and no
currency. The result carries the fact's quote, page and status, so an unconfirmed amount is shown as such.
"""

import re
from dataclasses import dataclass
from typing import Any

_DIGITS = re.compile(r"[^\d.,]")


@dataclass(frozen=True)
class FundsResult:
    required: float | None  # None when the funds fact is missing
    base: float | None  # the fact's amount for a full year
    months: int
    reduction: float
    currency_label: str
    status: str  # the fact's status (confirmed, unconfirmed, stale), or "missing"
    quote: str | None
    url: str | None


def as_number(value: Any) -> float | None:
    """A read amount as a number: 11904, "11,904.00", "11.904,00", "992,50", "11 904" with a label. None if unreadable."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = _DIGITS.sub("", str(value))
    if not re.search(r"\d", text):
        return None
    if "," in text and "." in text:  # the later one is the decimal separator
        decimal = "," if text.rfind(",") > text.rfind(".") else "."
        text = text.replace("." if decimal == "," else ",", "").replace(",", ".")
    elif "," in text or "." in text:
        sep = "," if "," in text else "."
        head, _, tail = text.rpartition(sep)
        if text.count(sep) == 1 and len(tail) != 3:  # one separator, not followed by 3 digits: a decimal point
            text = f"{head.replace(sep, '')}.{tail}"
        else:  # thousands separators
            text = text.replace(sep, "")
    try:
        return float(text)
    except ValueError:
        return None


def required_funds(funds, fact, reduction: float) -> FundsResult:
    """`funds` is the config's Funds; `fact` is the route's knowledge Fact (or None); `reduction` the student's
    other proof, in the same currency."""
    reduction = max(0.0, float(reduction or 0))
    base = as_number(fact.value) if fact is not None else None
    if base is None:
        return FundsResult(None, None, funds.months, reduction, funds.currency_label, "missing",
                           None if fact is None else fact.quote, None if fact is None else fact.url)
    required = round(max(0.0, base * funds.months / 12 - reduction), 2)
    return FundsResult(required, base, funds.months, reduction, funds.currency_label, fact.status, fact.quote, fact.url)
