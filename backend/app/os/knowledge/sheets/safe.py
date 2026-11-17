"""Spreadsheet safety: a cell that starts like a formula is neutralised before it is written to a CSV or workbook
(CSV / formula injection). The text is kept, with a leading apostrophe."""

from typing import Any

_RISKY = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: Any) -> Any:
    # leading spaces do not hide a formula from a spreadsheet, so they are looked through too
    if isinstance(value, str) and (value.startswith(_RISKY) or value.lstrip().startswith(_RISKY)):
        return "'" + value
    return value


def unsafe_cell(value: Any) -> Any:
    """The inverse of `safe_cell` on read: one leading apostrophe is taken off when the rest of the cell starts like a
    formula, so what we wrote comes back as it was (R-69 round trip). Any other leading apostrophe is the text's own."""
    if isinstance(value, str) and value.startswith("'") and len(value) > 1:
        rest = value[1:]
        if rest.startswith(_RISKY) or rest.lstrip().startswith(_RISKY):
            return rest
    return value
