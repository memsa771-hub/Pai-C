"""Loads a hand-written Knowledge seed (YAML). Insert-only: re-running it never changes an existing fact
(handoff M6), so a confirmed or researched fact survives a re-seed."""

from datetime import date, datetime, time, timezone
from pathlib import Path

import yaml

from app.os.knowledge.port import Fact
from app.os.knowledge.store import SqlKnowledge

SEED_DIR = Path(__file__).parent / "seed"


def _checked_at(raw) -> datetime:
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    if isinstance(raw, date):
        return datetime.combine(raw, time(), tzinfo=timezone.utc)
    return datetime.combine(date.fromisoformat(str(raw)), time(), tzinfo=timezone.utc)


def _fact(raw: dict, intake_year: int) -> Fact:
    return Fact(
        value=raw.get("value"), quote=raw.get("quote") or "", url=raw.get("url") or "",
        checked_at=_checked_at(raw["checked_at"]), intake_year=intake_year, status=raw["status"],
        conflict_note=raw.get("conflict_note"),
    )


def load_seed(path: Path, store: SqlKnowledge) -> int:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    year = int(data["intake_year"])
    count = 0
    for field, raw in (data.get("route") or {}).items():
        store.insert_if_absent("route", data["route_key"], field, _fact(raw, year))
        count += 1
    for ref, fields in (data.get("programmes") or {}).items():
        for field, raw in fields.items():
            store.insert_if_absent("programme", ref, field, _fact(raw, year))
            count += 1
    return count
