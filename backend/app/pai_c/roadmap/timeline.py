"""How long a route takes: months to entry and years to finish, from the
coloured steps and the dated academic calendar (spec FOUR_FEATURES_SPEC.md
§4.2).

Pure: `today` is passed in (routers pass the request day, tests freeze it).
The walk follows the steps still to do in route order. A step's chain events
happen one after another, each strictly after the event before it (Part-1
result, then the Part-2 exam, then the entry test); a step's result is a gate
the intake waits for that nothing chains after, because students sit entry
tests between their exams and their results. Entry is the first intake start
in or after the month of the last event: the 2026 cycle announced results in
the month its intakes opened. A month nobody found leaves that step "date not
confirmed" and the whole estimate uncertain; nothing is guessed.
"""

from datetime import date

from app.pai_c.roadmap import calendar as cal
from app.pai_c.roadmap.rules import rule_for

_WEAKEST = {name: rank for rank, name in enumerate(cal.CONFIDENCE)}

Month = tuple[int, int]  # (year, month)


def next_occurrence(months, after: Month | None, today: date, *, same_month: bool = False) -> Month | None:
    """The first (year, month) among `months` after `after` (strictly, unless
    same_month), or from today's month on when nothing came before. A month
    that has passed this year rolls to next year. None when no month is known."""
    months = sorted(set(months or ()))
    if not months:
        return None
    if after is None:
        year, month, same_month = today.year, today.month, True
    else:
        year, month = after
    later = [m for m in months if m > month or (same_month and m == month)]
    return (year, later[0]) if later else (year + 1, months[0])


def _basis(step_key: str | None, key: str | None, when: Month | None, row: dict | None) -> dict:
    return {"step": step_key, "event_key": key, "month": when[1] if when else None,
            "year": when[0] if when else None,
            "source": next((url for url in (row or {}).get("sources", ()) if url.startswith("https://")), None),
            "confidence": (row or {}).get("confidence")}


def _years(field_key: str | None) -> int | None:
    rule = rule_for(field_key) if field_key else None
    years = rule.years_for(field_key) if rule else None
    return years if years is not None else (cal.degree_years(field_key) if field_key else None)


def estimate(steps: list[dict], field_key: str | None, today: date) -> dict:
    previous: Month | None = None
    latest: Month = (today.year, today.month)
    basis, uncertain = [], False
    for step in steps:
        timing = step.get("timing")
        if step["status"] == "done" or not timing:
            continue
        if timing.get("unknown"):
            basis.append(_basis(step["key"], None, None, None))
            uncertain = True
            continue
        for key in timing.get("chain", ()):
            row = cal.event(key)
            when = next_occurrence(row["months"] if row else (), previous, today)
            basis.append(_basis(step["key"], key, when, row))
            if when is None:
                uncertain = True
                continue
            previous, latest = when, max(latest, when)
        if timing.get("result"):
            row = cal.event(timing["result"])
            when = next_occurrence(row["months"] if row else (), previous, today, same_month=True)
            basis.append(_basis(step["key"], timing["result"], when, row))
            if when is None:
                uncertain = True
            else:
                latest = max(latest, when)

    starts = []
    for intake in cal.intakes_for(field_key) if field_key else []:
        if intake.get("classes_start_month") is not None:
            when = next_occurrence([intake["classes_start_month"]], latest, today, same_month=True)
            starts.append((when, intake))
    next_intake = to_entry = to_finish = None
    if starts:
        when, intake = min(starts, key=lambda pair: pair[0])
        basis.append(_basis(None, intake["key"], when, intake))
        next_intake = {"label": intake["label"], "start_month": when[1], "year": when[0]}
        to_entry = max(0, (when[0] - today.year) * 12 + when[1] - today.month)
    else:
        uncertain = True
    years = _years(field_key)
    if to_entry is not None and years is not None:
        to_finish = round(to_entry / 12 + years, 1)
    else:
        uncertain = True
    known = [row["confidence"] for row in basis if row["confidence"]]
    confidence = ("uncertain" if uncertain or not known
                  else max(known, key=lambda name: _WEAKEST.get(name, len(_WEAKEST))))
    return {"to_entry_months": to_entry, "to_finish_years": to_finish, "next_intake": next_intake,
            "degree_years": years, "basis": basis, "confidence": confidence}
