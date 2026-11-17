"""The review queue as an R-67 spreadsheet (P2 spec §4.5, §4.6; master R-69).

Open items that carry a fact are written as rows of the Facts sheet in the one fixed format, with `fact_id` = `Q-<item id>`
and the checker columns empty. The same file is read by the normal import, so the queue and the spreadsheets never disagree.
Only facts about a registry entity, or about a programme placed under one, have a row: the sheet names its entity by the
institution's id. Others are listed in the second result, not dropped silently."""

import json
from pathlib import Path

from app.os.knowledge.fact_classes import fact_class, is_high_stakes
from app.os.knowledge.review.queue import Item, ReviewQueue
from app.os.knowledge.sheets.template import queue_export


def _entity(queue: ReviewQueue, scope: str, ref: str) -> str | None:
    """The sheet's entity id (the registry id without its kind prefix), or None when the fact has no registry entity."""
    if scope == "registry":
        return ref.partition(":")[2] or ref
    from app.os.knowledge.programmes import ProgrammeStore

    programme = ProgrammeStore(queue.engine, queue.tenant_id).get(ref) if scope == "programme" else None
    inst = getattr(programme, "institution_id", None)
    return inst.partition(":")[2] or inst if inst else None


def _value_cell(value) -> str:
    if isinstance(value, dict) and "value" in value:
        return str(value["value"])
    if isinstance(value, dict) and "date" in value:
        return str(value["date"])
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _intake_cell(term: str, year: int) -> str:
    """The intake as the sheet's text rules read it back (P2 spec §11.3): `Fall 2027`, a session as `2026-27`, a bare year."""
    if term == "session":
        return f"{year}-{(year + 1) % 100:02d}"
    return f"{term.capitalize()} {year}".strip() if term else str(year)


_METHOD = {"model": "webfetch (model-extracted)", "ocr": "ocr (machine-read)", "human": "human (by hand)",
           "render": "render", "fetch": "fetch", None: "fetch"}


def export_rows(queue: ReviewQueue, items: list[Item]) -> tuple[list[dict], list[int]]:
    """(rows for the Facts sheet, ids of the items that have no row)."""
    rows, skipped = [], []
    for item in items:
        if item.fact_id is None:
            skipped.append(item.id)
            continue
        scope, ref, field, fact = queue.knowledge.get(item.fact_id)
        entity = _entity(queue, scope, ref)
        if entity is None:
            skipped.append(item.id)
            continue
        high = is_high_stakes(fact_class(field, fact.fact_class))
        rows.append({
            "fact_id": f"Q-{item.id}", "entity_id": entity, "field": field, "value": _value_cell(fact.value),
            "unit": "date" if isinstance(fact.value, dict) and "date" in fact.value else None,
            "intake": _intake_cell(fact.intake_term, fact.intake_year), "high_stakes": "Y" if high else "N",
            "source_url": fact.url or None, "source_type": None, "quote_verbatim": fact.quote or None,
            "language": fact.language, "read_method": _METHOD.get(fact.read_method, "fetch"),
            "retrieved": fact.checked_at.date().isoformat(),
            "claude_status": "found" if fact.status in ("confirmed", "verified") else "unconfirmed",
            "claude_note": f"queue item {item.id} ({item.kind})"})
    return rows, skipped


def export_queue(queue: ReviewQueue, path: Path, *, status: str | None = "open", kind: str | None = None,
                 batch_ref: str | None = None) -> tuple[Path, int, list[int]]:
    """Writes the filtered queue as a batch file. Returns (path, rows written, ids of the items without a row)."""
    rows, skipped = export_rows(queue, queue.list_items(status=status, kind=kind, batch_ref=batch_ref, limit=10_000))
    return queue_export(rows, path), len(rows), skipped
