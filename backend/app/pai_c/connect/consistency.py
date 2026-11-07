"""The consistency rules 1-8 of master section 9.3 (P1-T10, R-05, R-04): the Counsellor side and the pure comparison.

`counsellor_side(db, workspace_id)` reads one student's Counsellor state into a frozen `CounsellorSide`: keys, versions,
codes, ids and times, never a Vault value or a student sentence. `check(c, o, ...)` compares it with the PAI OS view `o`
(`OsSideLike`, the shape of the OS read-only consistency view; this module imports nothing from `app.os`) and returns
findings. `check` does no IO. It reads and writes nothing: only the glue opens cases (R-01: the job repairs nothing).

Modes: `nightly` treats work younger than `IN_FLIGHT_SECONDS` (two sweeps) as in flight; `settled` (the end-of-test
check, run just after a sweep) tolerates nothing pending. Only portable SQL here (SQLite in tests, Postgres in prod).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from sqlalchemy import select

IN_FLIGHT_SECONDS = 600  # two sweeps of 300 s (D-z2)
OS_PART_OF_RULE = {1: "CONNECT_HANDOFF", 2: "CONNECT_HANDOFF", 3: "CONNECT_HANDOFF", 4: "CONNECT_ROADMAP_FROM_PLANVIEW",
                   5: "CONNECT_STUDENT_FACTS", 6: "CONNECT_ONE_UPLOAD", 7: "CONNECT_STUDENT_FACTS",
                   8: "CONNECT_HANDOFF"}  # the connection part each rule needs (§1: a rule runs only while its part is on)
HELD_INTAKE = ("planned", "revised", "replaced", "refused", "held", "paused")  # an intake outcome that settles rule 1
PLAN_OPEN = ("active", "at_risk", "paused")  # the OS plan statuses still being worked on (app.os.kernel.states)
PLAN_SOURCE = "counsellor"
WITHDRAWN_PREFIX = "withdrawn"  # the close reason the OS intake writes for a withdrawal: `withdrawn:{decision_id}`
Mode = Literal["nightly", "settled"]


# --- the Counsellor side -----------------------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionView:
    """The newest decision version of the student."""
    version: int
    status: str  # chosen | withdrawn
    os_supported: bool
    field_key: str | None
    place_refs: tuple[str, ...]
    place_fields: tuple[str, ...]  # study field keys of the student's stage H programmes that these places name
    chosen_at: datetime | None


@dataclass(frozen=True)
class OutboxItem:
    key: str
    kind: str  # decision | vault_event
    version: int | None  # the decision or Vault version in the key
    status: str  # pending | delivered | not_sent
    code: str | None  # `last_error`: a code, never a message
    created_at: datetime | None


@dataclass(frozen=True)
class CounsellorSide:
    workspace_id: str
    newest: DecisionView | None = None
    ticked_supported_versions: tuple[int, ...] = ()  # os_supported versions whose Counsellor checklist has a tick
    outbox: tuple[OutboxItem, ...] = ()
    export: Mapping[str, Any] | None = None  # `decision_record_v2` of the newest version (ids, versions, hashes' input)
    vault_version: int = 0
    excluded_fields: tuple[str, ...] = ()
    stage_h_fields: tuple[str, ...] = ()
    path_fields: tuple[str, ...] = ()  # fields of open paths the student ruled out and did not restore
    live_file_ids: frozenset[str] = frozenset()
    trashed_file_ids: frozenset[str] = frozenset()
    roadmap_kind: str | None = None  # "os" when the roadmap serves OS steps, "checklist" when it serves today's; None unread


@dataclass(frozen=True)
class Finding:
    rule: int
    codes: tuple[str, ...]
    plan_id: int | None = None


# --- the OS side, as the rules read it (A1's `OsSide` matches this) ---------------------------------------------

class PlanLike(Protocol):
    id: int
    source: str
    status: str
    close_reason: str | None
    decision_version: int | None
    contract_matches_export: bool
    export_hash_matches: bool


class OsSideLike(Protocol):
    latest_version: int | None
    intake_status_by_version: Mapping[int, str]
    refusal_by_version: Mapping[int, str | None]
    plans: Sequence[PlanLike]
    latest_vault_version: int | None
    unprocessed_fact_events: Sequence[Any]  # an age in seconds, or an object with `age_seconds`
    needed_file_refs: Sequence[str]
    duplicate_requests: Sequence[Any]


# --- reading the Counsellor side ---------------------------------------------------------------------------------

def _utc(at):
    if at is not None and at.tzinfo is None:
        return at.replace(tzinfo=timezone.utc)
    return at


def _key_version(key: str) -> int | None:
    tail = key.rsplit(":", 1)[-1]
    return int(tail) if tail.isdigit() else None


def _stage_h(db, workspace_id: str) -> dict[str, set[str]]:
    """Study field key -> the programme refs of the student's completed programme searches for that field."""
    from app.models import ExecutionRun, PaiPossibility

    found: dict[str, set[str]] = {}
    runs = db.scalars(select(ExecutionRun).where(ExecutionRun.workspace_id == workspace_id,
                                                  ExecutionRun.task_type == "program_search",
                                                  ExecutionRun.status == "completed")).all()
    for run in runs:
        result = (run.result or {}).get("capability_result") or {}
        refs = {p.get("opportunity_id") for p in result.get("programs", []) if p.get("opportunity_id")}
        if not refs:
            continue
        row = db.get(PaiPossibility, (run.constraints or {}).get("possibility_id"))
        key = ((row.study_field or {}).get("key") if row is not None else None)
        if key:
            found.setdefault(key, set()).update(refs)
    return found


def _roadmap_kind(db, row, parts) -> str | None:
    """What the roadmap serves for the active supported choice, read through `plan_adapter` (never re-rendered)."""
    if row is None or row.status != "chosen" or not row.os_supported:
        return None
    from app.pai_c.roadmap import plan_adapter

    try:
        view = plan_adapter.read(row)
    except Exception:  # noqa: BLE001 - an unreadable OS is not a finding (the OS is reported by its own port)
        return None
    if view is None:
        return None
    return "os" if view.get("state") != "empty" and plan_adapter.applied(row, view) else "checklist"


def counsellor_side(db, workspace_id: str) -> CounsellorSide:
    """One student's Counsellor state. Keys, versions, ids and times only. Reads, never writes."""
    from app.models import (
        FileRecord,
        OsOutbox,
        PaiPossibility,
        RouteDecision,
        VaultVersion,
    )
    from app.pai_c.os_export import decision_record_v2
    from app.pai_c.paths.exclusions import _OPEN, _restored, excluded_fields

    rows = db.scalars(select(RouteDecision).where(RouteDecision.workspace_id == workspace_id)
                      .order_by(RouteDecision.decision_version.desc())).all()
    stage_h = _stage_h(db, workspace_id)
    excluded = excluded_fields(db, workspace_id)
    newest = None
    if rows:
        row = rows[0]
        refs = tuple(p["programme_ref"] for p in row.places or [])
        newest = DecisionView(
            version=row.decision_version, status=row.status, os_supported=bool(row.os_supported),
            field_key=row.field_key, place_refs=refs, chosen_at=_utc(row.chosen_at),
            place_fields=tuple(sorted(k for k, programs in stage_h.items() if programs & set(refs))))
    items = db.scalars(select(OsOutbox).where(OsOutbox.workspace_id == workspace_id)
                       .order_by(OsOutbox.created_at, OsOutbox.key)).all()
    vault = db.get(VaultVersion, workspace_id)
    paths = db.scalars(select(PaiPossibility).where(PaiPossibility.workspace_id == workspace_id)).all()
    path_fields = sorted({(p.study_field or {}).get("key") for p in paths
                          if p.status in _OPEN and (p.study_field or {}).get("key") in excluded
                          and not _restored(p, excluded[(p.study_field or {})["key"]])})
    live, trashed = set(), set()
    for f in db.execute(select(FileRecord.id, FileRecord.status, FileRecord.deleted_at)
                        .where(FileRecord.workspace_id == workspace_id)):
        (trashed if f.status == "deleted" or f.deleted_at is not None else live).add(f.id)
    return CounsellorSide(
        workspace_id=workspace_id, newest=newest,
        ticked_supported_versions=tuple(sorted(r.decision_version for r in rows if r.os_supported and r.steps_done)),
        outbox=tuple(OutboxItem(i.key, i.kind, _key_version(i.key), i.status, i.last_error, _utc(i.created_at))
                     for i in items),
        export=decision_record_v2(db, rows[0]) if rows else None,
        vault_version=vault.version if vault is not None else 0,
        excluded_fields=tuple(sorted(excluded)), stage_h_fields=tuple(sorted(stage_h)),
        path_fields=tuple(path_fields), live_file_ids=frozenset(live), trashed_file_ids=frozenset(trashed),
        roadmap_kind=_roadmap_kind(db, rows[0] if rows else None, None))


# --- the rules (pure) --------------------------------------------------------------------------------------------

def _age(item, now: datetime) -> float:
    if isinstance(item, (int, float)):
        return float(item)
    if hasattr(item, "age_seconds"):
        return float(item.age_seconds)
    at = _utc(getattr(item, "at", item))
    return (now - at).total_seconds() if isinstance(at, datetime) else 0.0


def _in_flight(item: OutboxItem | None, mode: Mode, now: datetime) -> bool:
    """A pending outbox row young enough to be on its way (nightly only)."""
    return (mode == "nightly" and item is not None and item.status == "pending" and item.created_at is not None
            and (now - item.created_at).total_seconds() < IN_FLIGHT_SECONDS)


def _decision_row(c: CounsellorSide, version: int) -> OutboxItem | None:
    return next((i for i in c.outbox if i.kind == "decision" and i.version == version), None)


def _open_counsellor_plans(o) -> list:
    return [p for p in o.plans if p.source == PLAN_SOURCE and p.status in PLAN_OPEN]


def _rule1(c, o, mode, now):
    n = c.newest
    if n is None or n.status != "chosen" or not n.os_supported:
        return []
    row = _decision_row(c, n.version)
    if row is not None and row.status == "not_sent" and row.code:
        return []  # a recorded refusal on the Counsellor side
    if _in_flight(row, mode, now):
        return []
    latest = o.latest_version
    if latest is not None and latest > n.version:
        return [Finding(1, ("version_ahead",))]
    if latest is not None and latest < n.version:
        return [Finding(1, ("version_behind",))]
    status = o.intake_status_by_version.get(n.version)
    settled = latest == n.version and status in HELD_INTAKE
    if settled and (o.refusal_by_version.get(n.version) or any(
            p.source == PLAN_SOURCE and p.decision_version == n.version and p.status in PLAN_OPEN for p in o.plans)):
        return []
    return [Finding(1, ("no_plan",))]


def _rule2(c, o, mode, now):
    n = c.newest
    found = []
    for plan in _open_counsellor_plans(o):
        if n is None:
            found.append(Finding(2, ("plan_without_decision",), plan.id))
        elif n.status == "chosen" and n.os_supported and plan.decision_version == n.version:
            codes = (("contract_hash",) if not plan.contract_matches_export else ()) + (
                ("export_hash",) if not plan.export_hash_matches else ())
            if codes:
                found.append(Finding(2, codes, plan.id))
    return found


def _rule3(c, o, mode, now):
    n = c.newest
    if n is None or n.status != "withdrawn" or _in_flight(_decision_row(c, n.version), mode, now):
        return []
    return [Finding(3, ("plan_not_stopped",), p.id) for p in _open_counsellor_plans(o)]


def _rule4(c, o, mode, now):
    n, codes = c.newest, []
    if c.ticked_supported_versions:
        codes.append("checklist_ticked")
    if n is not None and n.status == "chosen" and not n.os_supported and _open_counsellor_plans(o) \
            and not _in_flight(_decision_row(c, n.version), mode, now):
        codes.append("plan_for_unsupported")
    if n is not None and n.status == "chosen" and n.os_supported and c.roadmap_kind not in (None, "os") and any(
            p.decision_version == n.version for p in _open_counsellor_plans(o)):
        codes.append("checklist_served")
    return [Finding(4, tuple(codes))] if codes else []


def _rule5(c, o, mode, now):
    if c.vault_version <= 0:
        return []
    codes = []
    if (o.latest_vault_version or 0) < c.vault_version:
        event = next((i for i in c.outbox if i.kind == "vault_event" and i.version == c.vault_version), None)
        if not _in_flight(event, mode, now):
            codes.append("vault_behind")
    events = o.unprocessed_fact_events
    if mode == "nightly":
        events = [e for e in events if _age(e, now) >= IN_FLIGHT_SECONDS]
    if events:
        codes.append("replan_pending")
    return [Finding(5, tuple(codes))] if codes else []


def _rule6(c, o, mode, now):
    codes = set()
    for ref in o.needed_file_refs:
        if ref in c.trashed_file_ids:
            codes.add("file_trashed")
        elif ref not in c.live_file_ids:
            codes.add("file_missing")
    return [Finding(6, tuple(sorted(codes)))] if codes else []


def _rule7(c, o, mode, now):
    return [Finding(7, ("duplicate_request",))] if o.duplicate_requests else []


def _rule8(c, o, mode, now):
    excluded, n, codes = set(c.excluded_fields), c.newest, []
    if not excluded:
        return []
    if n is not None and n.status == "chosen":
        if n.field_key in excluded:
            codes.append("in_choice")
        if excluded & set(n.place_fields):
            codes.append("in_places")
    if excluded & set(c.stage_h_fields):
        codes.append("in_stage_h")
    if excluded & set(c.path_fields):
        codes.append("in_paths")
    return [Finding(8, tuple(codes))] if codes else []


_RULES = {1: _rule1, 2: _rule2, 3: _rule3, 4: _rule4, 5: _rule5, 6: _rule6, 7: _rule7, 8: _rule8}


def check(c: CounsellorSide, o: OsSideLike, *, mode: Mode, now: datetime,
          parts: frozenset[str] | set[str] | None = None) -> list[Finding]:
    """Rules 1-8 over one student. `parts`: the connection parts that are on (None: all); a rule whose part is off is
    skipped. Pure: no IO, no clock (`now` is passed). One Finding per rule (rules 2 and 3 one per plan)."""
    if mode not in ("nightly", "settled"):
        raise ValueError(mode)
    now = _utc(now)
    found: list[Finding] = []
    for rule, fn in _RULES.items():
        if parts is None or OS_PART_OF_RULE[rule] in parts:
            found.extend(fn(c, o, mode, now))
    return found
