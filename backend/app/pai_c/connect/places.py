"""Data behind the choice screen (P1-T3, D-f, D-g): country names to ISO, the destinations a student can pick, the
intake terms and the places for a route. Codes and IDs only; countries, terms and routes live in data files or come
from PAI OS through the bridge. Vault readers are small functions so tests can replace them."""

import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml

_DIR = Path(__file__).parent
MAX_PLACES = 5
DEFAULT_LEVEL = "bachelor"  # D-f: the next level of a student before or at intermediate


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip().casefold()


@lru_cache(maxsize=1)
def _countries() -> dict[str, str]:
    data = yaml.safe_load((_DIR / "countries.yaml").read_text(encoding="utf-8")) or {}
    return {_norm(name): code for name, code in data.items()}


@lru_cache(maxsize=1)
def _intakes() -> dict:
    return yaml.safe_load((_DIR / "intakes.yaml").read_text(encoding="utf-8"))


def to_iso(name) -> str | None:
    """ISO 3166-1 alpha-2 for a country name, ignoring case and spacing; None when the name is not in countries.yaml."""
    if not isinstance(name, str):
        return None
    return _countries().get(_norm(name))


def generic_terms() -> list[str]:
    return list(_intakes()["terms"])


def next_level(standing_level: str | None, field_key: str | None) -> str:
    """The level the student studies next. A degree student moves to the next level the field offers
    (study_fields.json `degree_levels` and the field's `levels`); anyone else starts at bachelor."""
    from app.pai_c.paths.fields import group_rules, study_fields

    nxt = group_rules()["degree_levels"].get(standing_level or "")
    if not nxt:
        return DEFAULT_LEVEL
    field = study_fields().get(field_key or "")
    for level in nxt:
        if field is not None and level in field.levels:
            return level
    return DEFAULT_LEVEL  # no known field, or the field offers no next level: the default


def _vault_value(db, workspace_id: str, key: str):
    from app.pai_c.memory import MemoryService

    row = MemoryService(db).profile(workspace_id).facts.get(key)
    return row["value"] if row else None


def vault_value(db, workspace_id: str, key: str):
    """The student's active Vault value for `key`, or None. The one reader for routers."""
    return _vault_value(db, workspace_id, key)


def _eligible_levels(db, workspace_id: str) -> list[str] | None:
    """The levels the student's education opens (eligible_levels.yaml); None when unknown."""
    from app.pai_c.connect.student_facts import student_eligible_levels

    return student_eligible_levels(db, workspace_id)


def _standing_level(db, workspace_id: str) -> str | None:
    from app.pai_c.memory import MemoryService
    from app.pai_c.roadmap.engine import student_standing

    cards = [c for c in MemoryService(db).profile_cards(workspace_id) if c["kind"] == "education"]
    return student_standing([c["value"] for c in cards]).level


def run_is_served(db, run, excluded: dict) -> bool:
    """Whether a completed programme search is still offered: false when its path's study field is one the student ruled
    out and did not restore (R-15). The one filter for the places the Counsellor serves and for the consistency check."""
    from app.models import PaiPossibility
    from app.pai_c.paths.exclusions import _restored

    if not excluded:
        return True
    path = db.get(PaiPossibility, (run.constraints or {}).get("possibility_id"))
    option = excluded.get((path.study_field or {}).get("key")) if path is not None else None
    return option is None or _restored(path, option)


def _stage_h_programs(db, workspace_id: str) -> list[dict]:
    """The student's current stage H programs (newest completed search first, each still fresh), as the programs
    endpoint shows them: `opportunity_id`, `title`, `country`."""
    from sqlalchemy import select

    from app.models import ExecutionRun
    from app.pai_c.memory import MemoryService
    from app.pai_c.paths.exclusions import excluded_fields
    from app.pai_c.paths.programs import current_programs

    runs = db.scalars(select(ExecutionRun).where(
        ExecutionRun.workspace_id == workspace_id, ExecutionRun.task_type == "program_search",
        ExecutionRun.status == "completed").order_by(ExecutionRun.created_at.desc())).all()
    facts = MemoryService(db).comparable_facts(workspace_id)
    excluded = excluded_fields(db, workspace_id)  # R-15: a field the student ruled out offers no places
    seen, found = set(), []
    for run in runs:
        if not run_is_served(db, run, excluded):
            continue
        result = ((run.result or {}).get("capability_result") or {})
        current, _ = current_programs(db, workspace_id, result, facts)
        for program in current["programs"]:
            ref = program.get("opportunity_id")
            if ref and ref not in seen:
                seen.add(ref)
                found.append(program)
    return found


def _targets(db, workspace_id: str) -> list[str]:
    value = _vault_value(db, workspace_id, "preferences.target_countries")
    if isinstance(value, str):
        value = [value]
    return [v for v in (value or []) if isinstance(v, str)]


def choice_options(db, workspace_id: str, field_key: str | None, today: date | None = None) -> dict:
    """What the choice screen offers (D-f, D-g). Destinations: the home country plus the destination of every OS
    route at the level (from the student's origin when it is known), plus the one target country the Vault names when
    it is none of those (offered as unsupported). The level is always one the student's education opens
    (eligible_levels.yaml), when that is known. The target is pre-selected only when the Vault names exactly one
    and it maps to ISO. Terms per destination: the route's own, else the generic ones."""
    from app import pai_os_bridge

    today = today or date.today()
    level = next_level(_standing_level(db, workspace_id), field_key)
    eligible = _eligible_levels(db, workspace_id)
    if eligible and level not in eligible:  # R-14: a level the education does not open is never offered
        level = eligible[0]
    origin = to_iso(_vault_value(db, workspace_id, "location.current_country"))
    routes = [r for r in pai_os_bridge.list_routes() if r["level"] == level and (origin is None or r["origin"] == origin)]
    destinations: dict[str, dict] = {}
    terms: dict[str, list[str]] = {}

    def offer(code: str, route: dict | None) -> None:
        if code in destinations and destinations[code]["supported"]:
            return
        destinations[code] = {"code": code, "supported": route is not None,
                              "route_key": route["key"] if route else None}
        terms[code] = list(route["intake_terms"]) if route and route["intake_terms"] else generic_terms()

    if origin:
        offer(origin, next((r for r in routes if r["destination"] == origin), None))
    for route in routes:
        offer(route["destination"], route)
    targets = _targets(db, workspace_id)
    pre = to_iso(targets[0]) if len(targets) == 1 else None
    if pre and pre not in destinations:
        offer(pre, None)
    years = list(range(today.year, today.year + _intakes()["years_ahead"] + 1))
    return {"origin": origin, "level": level, "destinations": list(destinations.values()),
            "preselected_destination": pre, "intake_terms": terms, "years": years}


def places_for(db, workspace_id: str, destination: str, level: str, term: str, year: int) -> list[dict]:
    """The places to offer for a destination. A route PAI OS serves: its programme list for the intake. Otherwise the
    student's own stage H programs in that country (`opportunity_id` as `ref`), at most five."""
    from app import pai_os_bridge

    origin = to_iso(_vault_value(db, workspace_id, "location.current_country"))
    for route in pai_os_bridge.list_routes():
        if route["destination"] == destination and route["level"] == level and (origin is None or route["origin"] == origin):
            return pai_os_bridge.programmes_for(route["key"], term, year)
    return [{"ref": p["opportunity_id"], "name": p.get("title", "")}
            for p in _stage_h_programs(db, workspace_id) if to_iso(p.get("country")) == destination][:MAX_PLACES]
