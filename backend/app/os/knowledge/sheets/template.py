"""Writes an empty batch file (the template) and the review queue's export in the same format (P2 spec §4.6; master
R-67, R-69; P2-D17). The `Lists` sheet is read-only help: the allowed status, check and read-method values."""

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.os.knowledge.sheets.format import Format, load_format


def _lists(fmt: Format) -> list[tuple[str, list[str]]]:
    raw = fmt.raw
    return [
        ("claude_status", list(fmt.claude_statuses)),
        ("checker1_result", list(fmt.check1_results)),
        ("checker2_approved", sorted(fmt.check2_values)),
        ("source_type", sorted(set(raw["source_types"]["official"]) | set(raw["source_types"]["not_official"]))),
        ("read_method (examples)", ["fetch", "pdf parse", "pdf parse (OCR)", "webfetch (model-extracted)",
                                    "image (machine-read)", "human (collected by a checker)"]),
        ("high_stakes", ["Y", "N"]),
    ]


def write_workbook(path: Path, rows: dict[str, Iterable[dict[str, Any]]] | None = None, fmt: Format | None = None) -> Path:
    """An .xlsx with the Institutions, Programmes and Facts sheets (header and the given rows) and the Lists sheet."""
    import openpyxl

    fmt = fmt or load_format()
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name in ("Institutions", "Programmes", "Facts"):
        ws = wb.create_sheet(name)
        cols = fmt.all_columns(name)
        ws.append(list(cols))
        ws.freeze_panes = "A2"
        for r in (rows or {}).get(name, ()):
            ws.append([r.get(c) for c in cols])
    ws = wb.create_sheet("Lists")
    lists = _lists(fmt)
    ws.append([title for title, _ in lists])
    for i in range(max(len(v) for _, v in lists)):
        ws.append([v[i] if i < len(v) else None for _, v in lists])
    path = Path(path)
    wb.save(path)
    return path


def write_template(path: Path) -> Path:
    return write_workbook(path)


def queue_export(items: Iterable[dict[str, Any]], path: Path, fmt: Format | None = None) -> Path:
    """The review queue as a batch file (R-69). Each item is a dict with the fields of the Facts sheet it can fill
    (`entity_id`, `field`, `value`, `intake`, `source_url`, `quote_verbatim`, ...) plus `fact_id` and `status` (the row's
    Claude status). The checker columns are left empty for the reviewers; importing the returned file is the normal import,
    so the queue and the spreadsheets never disagree."""
    rows = []
    for n, it in enumerate(items, start=1):
        row = {k: it.get(k) for k in (fmt or load_format()).sheets["Facts"].columns}
        row["fact_id"] = it.get("fact_id") or f"Q-{n:04d}"
        row["claude_status"] = it.get("status") or it.get("claude_status") or "unconfirmed"
        rows.append(row)
    return write_workbook(path, {"Facts": rows}, fmt)
