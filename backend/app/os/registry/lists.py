"""Official lists as registry rows (P2 spec §4.1; master R-35a). An official list is named by its body, its URL, the
region and institution type it defines and the row count as published. The file shape is the one of the H3 research
(`docs/research/lists/*.yaml`): `region`, `retrieved`, `lists[]`. `domains` and `not_found` of such a file belong to the
allow-list (T3) and the walkthroughs, so they are ignored here. No list is written in code."""

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.os.knowledge.regions import UnknownRegion, normalise_region
from app.os.registry.model import RegistryEntry, slug
from app.os.registry.store import RegistryStore

_ATTRS = ("body", "count_quote", "count_conflict_quote", "count_method", "read_method", "status", "note", "family",
          "check2")
_KNOWN = {"id", "name", "url", "institution_type", "date", "row_count", *_ATTRS}


class OfficialListError(ValueError):
    pass


def _day(value: Any, where: str) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    raise OfficialListError(f"{where}: 'retrieved' must be a date")


def parse_official_lists(data: dict, *, country: str) -> list[RegistryEntry]:
    """The `official_list` entries of one list file. `country` selects the region vocabulary the file's region is
    normalised with. Raises `OfficialListError` naming the list that is wrong."""
    if not isinstance(data, dict) or "region" not in data or "lists" not in data:
        raise OfficialListError("a list file has 'region', 'retrieved' and 'lists'")
    try:
        region = normalise_region(str(data["region"]), country)
    except UnknownRegion as e:
        raise OfficialListError(f"region: {e}") from e
    retrieved = _day(data.get("retrieved"), "file")
    out: list[RegistryEntry] = []
    seen: set[str] = set()
    for item in data["lists"] or []:
        where = f"list '{item.get('id', '?')}'"
        try:
            lid = f"list:{slug(str(item['id']))}"
            if lid in seen:
                raise OfficialListError(f"{where}: listed twice")
            seen.add(lid)
            count = item.get("row_count")
            if count is not None and (isinstance(count, bool) or not isinstance(count, int) or count < 0):
                raise OfficialListError(f"{where}: row_count must be a whole number or null")
            attrs: dict[str, Any] = {k: item[k] for k in _ATTRS if item.get(k) is not None}
            attrs["row_count"] = count
            attrs["date"] = item["date"].isoformat() if item.get("date") else None
            attrs["count_confirmed"] = item.get("check2") == "correct"
            extra = {k: v for k, v in item.items() if k not in _KNOWN}
            if extra:
                attrs["extra"] = extra
            out.append(RegistryEntry(
                entity_id=lid, kind="official_list", name=str(item["name"]), source_url=str(item["url"]),
                checked_at=retrieved, quote=str(item.get("count_quote") or ""), region=region,
                institution_type=item.get("institution_type"), attrs=attrs))
        except OfficialListError:
            raise
        except KeyError as e:
            raise OfficialListError(f"{where}: missing {e}") from e
        except ValueError as e:
            raise OfficialListError(f"{where}: {e}") from e
    return out


def load_official_lists(store: RegistryStore, path: Path, *, country: str, cause_ref: str | None = None,
                        actor: str | None = None) -> int:
    """Records every list of a file (all or none are parsed first). Recording an unchanged list writes nothing."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise OfficialListError(f"{path.name}: {e}") from e
    entries = parse_official_lists(data, country=country)
    for entry in entries:
        store.record(entry, cause="import", cause_ref=cause_ref, actor=actor)
    return len(entries)
