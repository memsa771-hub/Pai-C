"""Per-value answers noted on a conflict card (P1-T8 owner ruling: one value at a time).

The card keeps the document's reading exactly as it was (`evidence.proposed` and the proposing candidate are never
changed). What the student answered is noted apart, in `evidence.os_answers[key]`: `{choice, field, value, request_id?}`,
`field` the record field the answer is about and `value` the value the Vault held after the answer (an audit note). Three places
read it:

- the code that picks the next question (an answered key is not asked again);
- the card's resolution, which leaves the answered fields out of the record it applies, so a value the student refused
  cannot come back through "accept" and a later edit of the field is not reverted either (the reconciler's partial
  upsert keeps what the record holds now);
- the Vault page, which leaves answered fields out of the two values it shows."""

from typing import Any

KEY = "os_answers"
LEVEL, SCORE = "level", "overall_score"  # fields that are not under `result`


def answers_of(issue) -> dict:
    found = (issue.evidence or {}).get(KEY)
    return found if isinstance(found, dict) else {}


def _path(field: str) -> tuple[str, ...]:
    if field == LEVEL:
        return ("qualification_name",)
    if field == SCORE:
        return (SCORE,)
    return ("result", *field.split("."))


def paths(answers: dict) -> set[tuple[str, ...]]:
    return {_path(a["field"]) for a in answers.values() if isinstance(a, dict) and a.get("field")}


def put(record: Any, field: str, raw: Any) -> Any:
    """A copy of a record dict whose `field` holds `raw`; anything else is returned as it is."""
    if not isinstance(record, dict):
        return record
    out = dict(record)
    node = out
    *parents, leaf = _path(field)
    for part in parents:
        node[part] = dict(node.get(part) or {})
        node = node[part]
    node[leaf] = raw
    return out


def drop(record: Any, answers: dict) -> Any:
    """A copy of a record dict without the fields the answers are about."""
    if not isinstance(record, dict) or not answers:
        return record

    def walk(node: dict, prefix: tuple, gone: set) -> dict:
        out = {}
        for name, item in node.items():
            here = (*prefix, name)
            if here in gone:
                continue
            out[name] = walk(item, here, gone) if isinstance(item, dict) else item
        return out

    return walk(record, (), paths(answers))
