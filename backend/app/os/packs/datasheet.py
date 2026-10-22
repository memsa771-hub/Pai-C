"""The data sheet (Slice 6a spec S6a-D4): every field of the route's list, from the student's confirmed profile. A
missing value is a gap, never a guess."""

from dataclasses import dataclass

from app.os.packs.config import ENTERED
from app.os.packs.inputs import ENTERED_PREFIX, PackInputs, show


@dataclass(frozen=True)
class SheetRow:
    section: str
    key: str
    label: str
    value: str | None
    source: str | None  # "document" or "entered"; None when there is no value
    document_id: int | None
    gap: bool  # required and missing
    hint: str = ""


def data_sheet(inp: PackInputs) -> list[SheetRow]:
    rows = []
    for section in inp.cfg.data_sheet:
        for f in section.fields:
            v = inp.profile.get(ENTERED_PREFIX + f.key if f.source == ENTERED else f.source)
            value = None if v is None or v.value in (None, "") else show(v.value)
            rows.append(SheetRow(section.title, f.key, f.label, value, v.source if value else None,
                                 v.document_id if value else None, f.required and value is None, f.hint))
    return rows
