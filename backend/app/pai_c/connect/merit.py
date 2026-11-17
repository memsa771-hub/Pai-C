"""Merit answers from MeritCheck (P2 freeze exception 2, flag CONNECT_MERIT_ANSWERS; master §10, R-48, P2 spec §4.10).

With the part on, the path of the student's chosen field gets one merit item per chosen place, built in code from
PAI OS `MeritCheck` (through the bridge) and the sentences in merit_texts.yaml. The model never writes a merit figure
(path_analyzer.md still forbids it, and `sanitize` drops world numbers); the only merit data in a path comes from
here. With the part off, `attach` returns the paths unchanged, so the analyzer behaves as before.

The item's status is always `unknown`: a merit aggregate is not a verdict and never a chance (R-31)."""

import logging
from pathlib import Path
from urllib.parse import urlparse

import yaml

from app.config import config
from app.pai_c.connect.flags import part_on

logger = logging.getLogger(__name__)

PART = "CONNECT_MERIT_ANSWERS"
SOURCE = "merit_check"
TEXTS_PATH = Path(__file__).with_name("merit_texts.yaml")
_RANK = {"unknown": 0, "stated": 1, "shown": 2, "confirmed": 3}


def _load() -> dict:
    raw = yaml.safe_load(TEXTS_PATH.read_text(encoding="utf-8")) or {}
    for key in ("label", "place_fallback", "status", "evidence", "closing", "no_chance"):
        if key not in raw:
            raise ValueError(f"{TEXTS_PATH.name}: no {key}")
    return raw


_RAW = _load()


def _usable() -> bool:
    return bool(_RAW.get("approved")) or bool(config.CONNECT_CONSENT_DRAFT)


def _num(value: float) -> str:
    return f"{float(value):.2f}".rstrip("0").rstrip(".")


def _intake(intake: dict) -> str:
    term = intake.get("term")
    term = _RAW["closing"]["term_not_recorded"] if term in (None, "", "unrecorded") else term
    return f"({term} {intake.get('year')})"


def note_for(check: dict) -> str:
    """The note of one merit item, from a MeritCheck answer (`merit_check.v1` as JSON)."""
    status = _RAW["status"]
    parts = []
    if check["status"] == "computed":
        formula = check["formula"]
        host = urlparse(formula["source"]["url"]).hostname or ""
        parts.append(status["computed"].format(aggregate=_num(check["aggregate"]), total=_num(formula["total"]),
                                               source=host))
        weakest = min((m["evidence"] for m in check.get("marks_used") or []), key=_RANK.__getitem__, default="unknown")
        if _RAW["evidence"].get(weakest):
            parts.append(_RAW["evidence"][weakest])
    elif check["status"] == "missing":
        missing = [p["name"].replace("_", " ") for p in check.get("parts") or [] if p["status"] == "missing"]
        parts.append(status["missing"].format(parts=", ".join(missing)))
    elif check.get("formula"):
        parts.append(status["not_confirmed_marks"])
    else:
        parts.append(status["not_confirmed_formula"])
    for merit in check.get("closing_merits") or []:
        when = _intake(merit["intake"])
        if merit["level"] != "verified" or merit.get("value") is None:
            parts.append(_RAW["closing"]["not_confirmed"].format(intake=when))
        elif not merit["list_complete"]:
            parts.append(_RAW["closing"]["partial_list"].format(intake=when, value=_num(merit["value"]),
                                                                list=merit["list_number"]))
        else:
            parts.append(_RAW["closing"]["verified"].format(intake=when, value=_num(merit["value"])))
    parts.append(_RAW["no_chance"])
    return " ".join(parts)


def _names(db, workspace_id: str, row, term: str, year: int) -> dict[str, str]:
    from app.pai_c.connect.places import places_for

    try:
        return {p["ref"]: p.get("name") or "" for p in places_for(db, workspace_id, row.destination_country,
                                                                    row.level, term, year)}
    except Exception:  # noqa: BLE001  a name is a label only; the item falls back to "your choice N"
        logger.warning("merit_place_names_failed workspace_id=%s", workspace_id)
        return {}


def fit_items(db, workspace_id: str) -> tuple[str, list[dict]] | None:
    """(field_key, merit items) for the student's active choice, or None when there is no choice with places and an
    intake, or PAI OS answers nothing."""
    from app import pai_os_bridge
    from app.pai_c.roadmap.decisions import RouteDecisionService

    row = RouteDecisionService(db).active(workspace_id)
    if row is None or not row.places or not row.intake:
        return None
    term, year = row.intake.get("term"), row.intake.get("year")
    names = _names(db, workspace_id, row, term, year)
    items = []
    for place in sorted(row.places, key=lambda p: p["rank"]):
        check = pai_os_bridge.merit_check(str(workspace_id), place["programme_ref"], term, year)
        if check is None:
            continue
        name = names.get(place["programme_ref"]) or _RAW["place_fallback"].format(rank=place["rank"])
        items.append({"label": _RAW["label"].format(place=name), "status": "unknown", "note": note_for(check),
                      "evidence": [], "source": SOURCE})
    return (row.field_key, items) if items else None


def attach(db, workspace_id: str, paths: list[dict]) -> list[dict]:
    """The analyzer's sanitized paths, with merit items added to the chosen field's path while the part is on.
    Unchanged (the same list) while the part is off, the texts are not approved, or anything fails (logged)."""
    if not part_on(PART) or not _usable():
        return paths
    try:
        found = fit_items(db, workspace_id)
    except Exception as exc:  # noqa: BLE001  the merit item never stops a path run
        logger.error("merit_items_failed workspace_id=%s error_type=%s", workspace_id, type(exc).__name__)
        return paths
    if found is None:
        return paths
    field_key, items = found
    out = []
    for path in paths:
        if (path.get("study_field") or {}).get("key") == field_key:
            path = {**path, "fit": [i for i in path["fit"] if i.get("source") != SOURCE] + items}
        out.append(path)
    return out
