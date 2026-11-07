"""Reads a returned batch (.xlsx, or a folder of CSV files named after the sheets) into canonical rows (P2-D17).

Older Programmes layouts are converted here by their mapping files (R-67, R-68); no row is edited by hand. Every row
keeps the row number it had in the file (`_row`), so a report can point to it."""

import csv
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.os.knowledge.sheets.format import Format, load_format

SHEETS = ("Institutions", "Programmes", "Facts")


class SheetError(ValueError):
    """The file cannot be read as a batch (a missing sheet or column). Nothing from it is loaded."""


@dataclass
class Batch:
    path: Path
    sha256: str
    sheets: dict[str, list[dict[str, Any]]]  # canonical rows, in file order
    layouts: dict[str, str] = field(default_factory=dict)  # sheet -> the legacy layout converted, if any
    blank_rows: dict[str, int] = field(default_factory=dict)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    if path.is_dir():
        for p in sorted(path.glob("*.csv")):
            h.update(p.name.encode() + p.read_bytes())
    else:
        h.update(path.read_bytes())
    return h.hexdigest()


def _clean(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def _raw_sheets(path: Path) -> dict[str, list[list[Any]]]:
    if path.is_dir():
        out = {}
        for name in SHEETS:
            f = path / f"{name}.csv"
            if f.is_file():
                with f.open(newline="", encoding="utf-8-sig") as fh:
                    out[name] = [list(r) for r in csv.reader(fh)]
        return out
    if path.suffix.lower() != ".xlsx":
        raise SheetError(f"{path.name}: a batch is an .xlsx file or a folder of CSV files")
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb if ws.title in SHEETS}
    finally:
        wb.close()


def _dicts(table: list[list[Any]]) -> tuple[list[str], list[dict[str, Any]]]:
    if not table:
        return [], []
    header = [str(h).strip() if h is not None else "" for h in table[0]]
    rows = []
    for n, r in enumerate(table[1:], start=2):
        d = {h: _clean(v) for h, v in zip(header, r) if h}
        d["_row"] = n
        rows.append(d)
    return header, rows


def _convert(fmt: Format, layout, rows: list[dict]) -> list[dict]:
    canonical = fmt.all_columns(layout.sheet)
    out = []
    for r in rows:
        note_extra = [f"{c}: {r[c]}" for c in layout.note_from if r.get(c) is not None]
        for part, emit in enumerate(layout.emit):
            if emit.get("when") and r.get(emit["when"]) is None:
                continue
            d: dict[str, Any] = {c: r.get(c) for c in canonical}
            for col, src in (emit.get("set") or {}).items():
                d[col] = src["const"] if isinstance(src, dict) else r.get(src)
            if note_extra:
                d["claude_note"] = " | ".join(filter(None, [d.get("claude_note"), *note_extra]))
            d["_row"], d["_part"] = r["_row"], part
            out.append(d)
    return out


def read_batch(path: Path, fmt: Format | None = None) -> Batch:
    """The canonical rows of a batch. Raises SheetError when a sheet or a required column is missing."""
    fmt = fmt or load_format()
    path = Path(path)
    if not path.exists():
        raise SheetError(f"{path}: no such file")
    raw = _raw_sheets(path)
    batch = Batch(path, file_sha256(path), {})
    missing_sheets = [s for s in ("Institutions", "Facts") if s not in raw]
    if missing_sheets:
        raise SheetError(f"{path.name}: missing sheet(s) {missing_sheets}")
    for name in SHEETS:
        header, rows = _dicts(raw.get(name, []))
        layout = next((l for l in fmt.layouts if l.sheet == name and set(l.detect) <= set(header)), None)
        if layout is not None:
            rows = _convert(fmt, layout, rows)
            batch.layouts[name] = layout.name
        else:
            spec = fmt.sheets[name]
            absent = [c for c in spec.required if rows is not None and header and c not in header]
            if name in raw and (absent or not header):
                raise SheetError(f"{path.name}: sheet {name} lacks required column(s) {absent or list(spec.required)}")
        key = fmt.sheets[name].key
        kept = []
        for r in rows:
            if all(r.get(c) is None for c in fmt.all_columns(name)):
                batch.blank_rows[name] = batch.blank_rows.get(name, 0) + 1
            else:
                for c in fmt.all_columns(name):
                    r.setdefault(c, None)
                kept.append(r)
        batch.sheets[name] = kept
    return batch
