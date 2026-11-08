"""Spreadsheet safety: a cell that starts like a formula is neutralised before it is written to a CSV or workbook
(CSV / formula injection). The text is kept, with a leading apostrophe."""

from typing import Any

_RISKY = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    if isinstance(value, str) and value.startswith(_RISKY):
        return "'" + value
    return value
