"""Decides, for every row of a batch, what happens to it (P2 spec §4.6 "Status mapping", P2-D16, P2-D16a; master R-68).

Pure: it reads nothing from the database and writes nothing. The same plan is what a dry run reports and what the import
then loads, so the two never differ. Buckets:

- `accepted`      loaded as `verified` or `confirmed` (see `level`; `needs_refetch` rows wait for the quote match);
- `unconfirmed`   loaded as `unconfirmed`, shown as "not confirmed yet";
- `queued`        not loaded; a review item is opened (`import_dispute`, `collect`);
- `rejected`      not loaded; listed in the import report with the reason;
- `skipped`       nothing to load by design (lead, history, searched-and-not-found, out of scope, aliased).

A row of an aliased id whose source is an official list is a list line naming an entity loaded under another id
(P2-T28): it loads no entity but adds that list to the target (reason `alias_membership`, `RegistryStore.add_lists`).

Alias files (aliases.py, P2-T13) are planned first, as rows of an `Aliases` sheet in the report: an accepted alias makes
the file's id name the entity already loaded under another id (in `Programmes.inst_id`, `Facts.entity_id` and
`Institutions.parent_id`). Aliases are new checks, so they are judged only by reviewer attestation, whatever the mode of
the rows.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.os.knowledge.fact_classes import fact_class as class_of_field
from app.os.knowledge.fact_classes import is_high_stakes
from app.os.knowledge.regions import UnknownRegion, normalise_region
from app.os.knowledge.sheets.aliases import AliasFile, bind
from app.os.knowledge.sheets.format import Format, load_format
from app.os.knowledge.sheets.reader import Batch
from app.os.registry.calendars import calendar_types
from app.os.registry.model import (KIND_PREFIX, NATIONAL, PROGRAMME_PARENTS, REGION_REQUIRED, SERVES_A_REGION,
                                   RegistryEntry, slug)

BUCKETS = ("accepted", "unconfirmed", "queued", "rejected", "skipped")
OWNER_ACCEPTED, REVIEWERS = "owner_accepted", "reviewers"
_SKIP_STATUS = {"superseded": "history", "lead_only": "lead", "not_found": "searched"}


@dataclass(frozen=True)
class Scope:
    """Where a page is read for: a region and family, or a route (the shape T3's allow-list expects)."""

    region: str = ""
    family: str = ""
    route_key: str = ""


@dataclass
class PlanContext:
    country: str
    mode: str = OWNER_ACCEPTED
    batch_ref: str = ""
    family: str = ""  # the --family given: the allow-list family of a row whose entity is on no list with a family
    attested: Callable[[str, str], bool] | None = None  # (reviewer ref, batch ref) -> bool; reviewer mode (T5)
    official: Callable[[str, Scope], bool] | None = None  # allow-list lookup (T3); None = not checked
    # official list URL -> its list id, or the ids of every list published at that URL (one page, several lists)
    list_urls: dict[str, str | tuple[str, ...]] = field(default_factory=dict)
    existing_institutions: Callable[[str], str | None] = lambda inst_id: None  # inst_id -> registry id already loaded
    existing_programmes: Callable[[str], bool] = lambda ref: False
    existing_region: Callable[[str], str | None] = lambda registry_id: None  # registry id -> region code
    existing_lists: Callable[[str], tuple[str, ...]] = lambda registry_id: ()  # registry id -> lists an import keeps
    list_regions: dict[str, str | None] = field(default_factory=dict)  # official list id -> its region code
    list_families: dict[str, str] = field(default_factory=dict)  # official list id -> its family (H3 data, P2-T19)
    existing_programme_institution: Callable[[str], str | None] = lambda ref: None  # a stored programme's institution
    lists_lookup: Callable[[str], tuple[str, ...]] = lambda registry_id: ()  # set by the plan: file, then database
    region_lookup: Callable[[str], str | None] = lambda registry_id: None  # set by the plan: file first, then database
    registry_info: Callable[[str], dict | None] = lambda registry_id: None  # a stored entity: kind, calendar_type, timezone, parent_id
    meta: Callable[[str], dict | None] = lambda registry_id: None  # set by the plan: file first, then database
    require_list: bool = True  # False only for a dry run that asks "what if every list were loaded"
    cap_without_allow_list: bool = False  # real imports: with no allow-list connected nothing is above `unconfirmed`
    decision_ref: str | None = None  # the owner's decision reference (owner-accepted mode)
    batch_sha: str = ""  # sha256 of the file being planned; set by plan_batch
    aliases: tuple[AliasFile, ...] = ()  # alias files for this file (P2-T13); bound to it by sha256 in plan_batch
    applied_aliases: dict[str, dict] = field(default_factory=dict)  # set by plan_batch: file id -> the applied alias
    refused_required: dict[str, str] = field(default_factory=dict)  # set by plan_batch: required alias not accepted (T28)
    fmt: Format = field(default_factory=load_format)


@dataclass
class RowResult:
    sheet: str
    row_id: str
    src_row: int
    bucket: str
    level: str | None = None  # verified | confirmed | unconfirmed, for loaded rows
    reason: str = ""
    detail: str = ""
    queue_kind: str | None = None  # import_dispute | collect | conflict
    needs_refetch: bool = False
    payload: dict[str, Any] = field(default_factory=dict)  # what the importer needs; not in the CSV report


def norm_url(u: str) -> str:
    return u.strip().rstrip("/").lower()


def lists_at(ctx: PlanContext, url: str | None, region: str | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(the lists a row from `url` is on, every list at `url`). A URL of one list: that list, as it is (its region is
    checked by the caller). A URL of several lists (one page, with regional views of it): the national ones among them
    and the ones of the row's region; none of them is a region conflict, for the caller to reject."""
    found = ctx.list_urls.get(norm_url(url or ""))
    every = (found,) if isinstance(found, str) else tuple(found or ())
    if len(every) <= 1:
        return every, every
    return tuple(x for x in every if ctx.list_regions.get(x, NATIONAL) in (NATIONAL, region)), every


def _date(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=UTC)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=UTC)
    if isinstance(v, str):
        m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", v.strip())
        if m:
            try:
                return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=UTC)
            except ValueError:
                return None
    return None


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _text(v: Any) -> str | None:
    return None if v is None else str(v).strip() or None


class Checks:
    """The two checks of a row, as the import accepts them (P2-D16, P2-D16a)."""

    def __init__(self, c1: str | None, c2: str | None, notes: list[str], provenance: dict):
        self.c1, self.c2, self.notes, self.provenance = c1, c2, notes, provenance


def read_checks(row: dict, ctx: PlanContext, *, mode: str | None = None, batch_ref: str | None = None) -> Checks:
    """`mode` and `batch_ref` override the context's (an alias is judged in reviewers mode against its own ref)."""
    fmt, mode = ctx.fmt, mode or ctx.mode
    batch_ref = ctx.batch_ref if batch_ref is None else batch_ref
    c1 = (_text(row.get("checker1_result")) or "").lower() or None
    c2 = fmt.check2_values.get((_text(row.get("checker2_approved")) or "").lower())
    n1, n2 = _text(row.get("checker1_name")), _text(row.get("checker2_name"))
    notes: list[str] = []
    if c1 is not None and c1 not in fmt.check1_results:
        notes.append(f"checker1_result '{c1}' is not allowed")
        c1 = None
    if mode == OWNER_ACCEPTED:
        r1, r2 = fmt.owner_accepted_ref(1, n1), fmt.owner_accepted_ref(2, n2)
        if c1 is not None and r1 is None:
            notes.append("checker 1 is not a check the owner accepted")
            c1 = None
        if c2 is not None and r2 is None:
            notes.append("checker 2 is not a check the owner accepted")
            c2 = None
        prov = {"checker1": r1, "checker2": r2, "checker1_name": n1, "checker2_name": n2}
    else:
        ok = lambda n: bool(n) and ctx.attested is not None and ctx.attested(n, batch_ref)  # noqa: E731
        if c1 is not None and not ok(n1):
            notes.append(f"checker 1 '{n1}' has not attested batch {batch_ref}")
            c1 = None
        if c2 is not None and (not ok(n2) or n2 == n1):
            notes.append("checker 2 is unknown, has not attested, or is checker 1 (two different people)")
            c2 = None
        prov = {"checker1": n1, "checker2": n2}
    return Checks(c1, c2, notes, prov)


def decide(status: str | None, chk: Checks, high_stakes: bool) -> tuple[str, str | None, str, str | None]:
    """(bucket, level, reason, queue_kind) from Claude's status and the checks. The README v4 rules (owner decision
    2026-11-07) and the spec's status mapping, in this order."""
    if status in _SKIP_STATUS:
        return "skipped", None, _SKIP_STATUS[status], None
    if status == "not_readable":  # nothing was read: a checker collects the official document (R-72)
        return "queued", None, "not_readable", "collect"
    if chk.c1 == "wrong":
        return "queued", None, "checker1_wrong", "import_dispute"
    if chk.c1 == "correct" and chk.c2 == "no":
        return "queued", None, "checker2_rejected", "import_dispute"
    if status == "conflict":
        return "unconfirmed", "unconfirmed", "conflict", "conflict"
    if chk.c1 == "correct":
        if chk.c2 == "yes":
            return "accepted", "verified", "both_checks", None
        return "accepted", "confirmed", "second_check_missing" if high_stakes else "one_check", None
    return "unconfirmed", "unconfirmed", "check_unclear_or_missing", None


def _source_problem(url: str | None, source_type: str | None, read_method: str | None, ctx: PlanContext) -> str | None:
    fmt = ctx.fmt
    if not url:
        return "bad_url"
    sp = urlsplit(url)
    if sp.scheme not in ("http", "https") or not sp.hostname:
        return "bad_url"
    if fmt.not_official_host(sp.hostname) or fmt.not_official_type(source_type):
        return "non_official_source"
    return None


def families(lists: tuple[str, ...] | list[str], ctx: PlanContext, kind: str | None = None) -> tuple[str, ...]:
    """The allow-list families to try for a row (P2-T19): the family of every official list its entity is on (H3 data,
    `family` of each list), in a fixed order. When none of them has a family: for a body (P2-T21, below) every family
    the run knows, else the `--family` given, which may be ''."""
    return family_choice(lists, ctx, kind)[0]


def family_choice(lists: tuple[str, ...] | list[str], ctx: PlanContext,
                  kind: str | None = None) -> tuple[tuple[str, ...], str]:
    """(families, basis). basis `lists`: the families of the entity's lists. basis `body_any` (P2-T21, controller
    decision under the owner's delegation of 2026-11-14): a body of a kind in `SERVES_A_REGION` (a regulator, board,
    admission body or system, entry test) on no list with a family serves its whole region, so it is tried under every
    family of the loaded official lists (`list_families`), the `--family` given first, then the others sorted. basis
    `run`: the `--family` given (every other kind, such as an institution, campus, calendar, seat category or list on no
    list with a family; an unknown kind; or no list family loaded at all). The region is never widened."""
    found = sorted({ctx.list_families[x] for x in lists if ctx.list_families.get(x)})
    if found:
        return tuple(found), "lists"
    known = sorted({f for f in ctx.list_families.values() if f})
    if kind in SERVES_A_REGION and known:
        return tuple(dict.fromkeys((*((ctx.family,) if ctx.family else ()), *known))), "body_any"
    return (ctx.family,), "run"


def _cap(result: RowResult, url: str, region: str | None, quote: str | None, ctx: PlanContext,
         read_method: str | None, lists: tuple[str, ...] = (), kind: str | None = None) -> None:
    """Things that stop a row above `unconfirmed`: no quote, off the allow-list, a model or OCR reading. The source
    passes the allow-list when its host is listed for the row's region and any family of the entity's lists; the scope
    that accepted it is kept in the row's provenance. Every row that gets here keeps the families it may be read for
    (`allow_list_families`), for the re-fetch of a row whose check did not reach this (P2-T19). `kind` is the kind of
    the entity whose lists these are (None: unknown); it decides the families of a body (P2-T21, `family_choice`)."""
    fams, basis = family_choice(lists, ctx, kind)
    result.payload["allow_list_families"] = fams
    if result.bucket not in ("accepted",):
        return
    if not quote:
        _lower(result, "no_quote")
        return
    if ctx.official is None and ctx.cap_without_allow_list:
        _lower(result, "allow_list_not_connected")  # no allow-list to check the source against: never above this
        return
    if ctx.official is not None:
        tried = [Scope(region=region or "", family=f) for f in fams]
        accepted = next((sc for sc in tried if ctx.official(url, sc)), None)
        if accepted is None:
            _lower(result, "source_not_on_allow_list")
            where = "scopes tried: " + ", ".join(f"{sc.region or '-'}/{sc.family or '-'}" for sc in tried)
            result.detail = "; ".join(x for x in (result.detail, where) if x)
            return
        prov = result.payload.setdefault("provenance", {})
        prov["allow_list_scope"] = {"region": accepted.region, "family": accepted.family}
        prov["family_basis"] = basis  # lists | body_any | run: why these families were tried (P2-T21)
    if read_method is None or read_method in ctx.fmt.needs_refetch:  # a missing read method is never assumed fetch
        if waiver_applies(ctx) and result.level == "verified":
            # owner ruling P2 spec §11.3: both AI checks accepted it, so no re-fetch; the waiver is on the record
            prov = result.payload.setdefault("provenance", {})
            prov["refetch_waived"] = ctx.fmt.raw["owner_accepted"]["refetch_waiver"]["ref"]
        else:
            result.needs_refetch = True


def waiver_applies(ctx: PlanContext) -> bool:
    """The §11.3 waiver: owner-accepted mode, a decision reference, and one of the five v4 files (by sha256)."""
    files = set(ctx.fmt.raw["owner_accepted"]["refetch_waiver"]["files"].values())
    return ctx.mode == OWNER_ACCEPTED and bool((ctx.decision_ref or "").strip()) and ctx.batch_sha in files


def _lower(result: RowResult, reason: str) -> None:
    result.bucket, result.level, result.reason = "unconfirmed", "unconfirmed", reason


def _region(text: str | None, kind: str | None, ctx: PlanContext) -> tuple[str | None, str | None]:
    """(code, problem). A region is required for some kinds; a given one must be in the vocabulary (R-76)."""
    if not text:
        return None, ("missing_region" if kind in REGION_REQUIRED else None)
    try:
        return normalise_region(text, ctx.country), None
    except UnknownRegion:
        return None, "unknown_region"


def resolve_aliases(ctx: PlanContext) -> tuple[list[RowResult], dict[str, dict]]:
    """(report rows, applied aliases: file id -> what provenance keeps). An alias is applied only when both checks accept
    it (check 1 correct, check 2 yes), the rule for rows, judged always in reviewers mode: both checkers attested the alias
    file's own ref (`AliasFile.attest_ref`, from its sha256) and checker 2 is not checker 1. The owner-accepted checker
    names never accept an alias: the owner's acceptance covers the batch rows checked on its date, not later checks.
    Any other alias is ignored and reported."""
    rows: list[RowResult] = []
    applied: dict[str, dict] = {}
    ctx.refused_required = {}
    for af in ctx.aliases:
        for a in af.aliases:
            chk = read_checks(a.checks, ctx, mode=REVIEWERS, batch_ref=af.attest_ref)
            res = RowResult("Aliases", a.from_id, a.index, "skipped")
            rows.append(res)
            if chk.c1 == "correct" and chk.c2 == "yes":
                res.bucket, res.reason, res.detail = "accepted", "alias_applied", f"{a.from_id} -> {a.to}"
                applied[a.from_id] = {"from": a.from_id, "to": a.to, "alias_file": af.path.name,
                                      "alias_sha256": af.sha256, "attest_ref": af.attest_ref,
                                      "evidence": {"url": a.evidence_url, "quote": a.evidence_quote},
                                      "checker1": chk.provenance.get("checker1"),
                                      "checker2": chk.provenance.get("checker2")}
                if a.required:
                    applied[a.from_id]["required"] = True
                if a.target_evidence:
                    applied[a.from_id]["target_evidence"] = dict(a.target_evidence)
            else:
                res.reason = "alias_not_accepted"
                res.detail = "; ".join(chk.notes) or f"check 1 {chk.c1 or 'missing'}, check 2 {chk.c2 or 'missing'}"
                if a.required:  # its id must not load as an entity of its own: every row naming it is rejected (T28)
                    res.bucket, res.reason = "rejected", "alias_required_not_accepted"
                    ctx.refused_required[a.from_id] = f"{a.from_id} -> {a.to} (required alias not accepted)"
    return rows, applied


def _aliased(r: dict, column: str, applied: dict[str, dict]) -> tuple[dict, dict | None]:
    """The row as planned: its id rewritten to an applied alias's target (a copy; the file's row is kept as read)."""
    used = applied.get(_text(r.get(column)) or "")
    return ({**r, column: used["to"], "_alias": used}, used) if used else (r, None)


def _note_alias(res: RowResult, original: dict, used: dict | None) -> None:
    """A row planned through an alias keeps the file's own row and records the alias in its provenance (R-76)."""
    if used is None:
        return
    if "row" in res.payload:
        res.payload["row"] = original
    if "provenance" in res.payload:
        res.payload["provenance"]["alias"] = dict(used)


def plan_institutions(batch: Batch, ctx: PlanContext, applied: dict[str, dict] | None = None) -> list[RowResult]:
    fmt, out, seen = ctx.fmt, [], set()
    planned: dict[str, str] = {}  # inst_id -> registry id of the rows planned so far (a parent comes before its child)
    first: dict[str, tuple[str, str | None]] = {}  # inst_id -> (kind, region) of its first row with an entry
    via_alias: list[tuple[RowResult, dict, dict | None]] = []
    memberships: list[tuple[RowResult, dict]] = []  # rows of an aliased id on an official list (P2-T28), planned last
    for original in batch.sheets["Institutions"]:
        r, used = _aliased(original, "parent_id", applied or {})  # before every other check
        rid = _text(r.get("inst_id")) or ""
        res = RowResult("Institutions", rid, r["_row"], "rejected")
        out.append(res)
        via_alias.append((res, original, used))
        if not rid:
            res.reason = "missing_id"
            continue
        refused = ctx.refused_required.get(rid) or ctx.refused_required.get(_text(original.get("parent_id")) or "")
        if refused:  # a required alias was not accepted: the id never loads as a new (duplicate) entity
            res.reason, res.detail = "alias_required_not_accepted", refused
            continue
        url = norm_url(_text(r.get("source_url")) or "")
        on, _ = lists_at(ctx, url, _region(_text(r.get("region")), None, ctx)[0])
        key = (rid, on or url)  # one row per id and list(s) (its URL while no list of it is loaded)
        if key in seen:
            res.reason = "duplicate_id"
            continue
        seen.add(key)
        member = bool(applied and rid in applied and lists_at(ctx, url, None)[1])  # a list line of the target (T28)
        if applied and rid in applied and not member:  # the entity is loaded under another id; this row loads nothing
            res.bucket, res.reason, res.detail = "skipped", "aliased", applied[rid]["to"]
            continue
        status = _text(r.get("claude_status"))
        if status not in fmt.claude_statuses:
            res.reason, res.detail = "bad_status", str(status)
            continue
        if (_text(r.get("in_scope")) or "yes").lower() in ("no", "n", "false"):
            res.bucket, res.reason = "skipped", "out_of_scope"
            continue
        if fmt.out_of_scope_region(_text(r.get("region"))):
            res.bucket, res.reason, res.detail = "skipped", "out_of_scope_region", str(r.get("region"))
            continue
        chk = read_checks(r, ctx)
        res.bucket, res.level, res.reason, res.queue_kind = decide(status, chk, False)
        res.detail = "; ".join(chk.notes)
        res.payload = {"row": r, "provenance": chk.provenance}
        if res.bucket in ("skipped", "queued"):
            res.level = None
            continue
        if member:
            memberships.append((res, r))
            continue
        problem, detail = _institution_entry(r, rid, res, ctx, planned, first)
        if problem:
            res.bucket, res.level, res.reason, res.detail, res.queue_kind = "rejected", None, problem, detail, None
    _plan_memberships(memberships, out, ctx, applied or {})
    for res, original, used in via_alias:
        _note_alias(res, original, used)
    return out


def _plan_memberships(memberships: list[tuple[RowResult, dict]], out: list[RowResult], ctx: PlanContext,
                      applied: dict[str, dict]) -> None:
    """P2-T28 (W12 "T28 rules"): a row of an applied alias whose source is an official list adds that list to the
    target instead of loading an entity (FU-3). Planned after every other row of the sheet, so the target may come
    anywhere in the file. A list the target already names (stored, or from its own rows in the file) adds nothing: the
    row stays `aliased`. A second row adding the same list to the same target is `duplicate_membership`."""
    file_targets: dict[str, dict] = {}  # inst_id -> what its loaded rows in this file give the entity
    for res in out:
        if "entry" in res.payload and res.bucket in ("accepted", "unconfirmed"):
            t = file_targets.setdefault(res.row_id, {"eid": res.payload["entry"].entity_id, "kind": res.payload["kind"],
                                                     "region": res.payload["entry"].region, "lists": ()})
            t["lists"] = tuple(dict.fromkeys((*t["lists"], *res.payload.get("lists", ()))))
    added: dict[str, tuple[str, ...]] = {}  # target -> lists the memberships of this file add or upgrade, in order
    for res, r in memberships:
        problem, detail = _membership(r, res, ctx, applied[res.row_id], file_targets, added)
        if problem:
            res.bucket, res.level, res.reason, res.detail, res.queue_kind = "rejected", None, problem, detail, None


def _membership(r: dict, res: RowResult, ctx: PlanContext, used: dict, file_targets: dict[str, dict],
                added: dict[str, tuple[str, ...]]) -> tuple[str | None, str]:
    fmt, to = ctx.fmt, used["to"]
    target = file_targets.get(to)
    if target is None:
        eid = ctx.existing_institutions(to)
        info = ctx.registry_info(eid) if eid else None
        if eid is None or not info or info.get("kind") not in ("institution", "campus") \
                or (info.get("status") or "active") != "active":  # closed, merged or renamed: never a list's target
            why = f"{info.get('kind')}, {info.get('status') or 'active'}" if info else "not loaded"
            return "alias_target_not_loaded", f"{to} ({why}); a list line adds a list only to a loaded institution"
        target = {"eid": eid, "kind": info["kind"], "region": ctx.existing_region(eid),
                  "lists": tuple(ctx.existing_lists(eid))}
    eid, tkind, tregion = target["eid"], target["kind"], target["region"]
    if tkind not in ("institution", "campus"):
        return "alias_target_not_loaded", f"{to} is a {tkind}; only an institution or campus is on a list"
    on, every = lists_at(ctx, r.get("source_url"), tregion)
    # the stored evidence of each list the target names (fix round 1): a weaker one may be upgraded by this line
    trust = (ctx.registry_info(eid) or {}).get("list_trust") or {}
    weaker = tuple(x for x in on if x in target["lists"] and x in trust
                   and TRUST_RANK.get(trust[x] or "", -1) < TRUST_RANK.get(res.level or "", -1))
    if on and all(x in target["lists"] for x in on) and not weaker:  # nothing to add or upgrade: as before T28
        res.bucket, res.level, res.reason, res.detail = "skipped", None, "aliased", to
        res.payload = {"row": r, "provenance": res.payload.get("provenance", {})}
        return None, ""
    kind = fmt.kind_of_type(_text(r.get("type")))
    if kind is None:
        return "unknown_type", str(r.get("type"))
    if kind != tkind:
        return "alias_kind_conflict", f"the row is a {kind}; the target {eid} is a {tkind}"
    url, quote = _text(r.get("source_url")), _text(r.get("source_quote"))
    rm_text = _text(r.get("read_method"))
    rm = fmt.read_method(rm_text)
    if rm is None:
        return "unknown_read_method", str(rm_text)
    if fmt.is_lead_read(rm_text):
        return "non_official_source", "read as a lead"
    prob = _source_problem(url, None, rm, ctx)
    if prob:
        return prob, str(url)
    region, rprob = _region(_text(r.get("region")), None, ctx)
    if rprob:
        return rprob, str(r.get("region"))
    if region is not None and region != tregion:  # an empty region takes the target's (rule 4)
        return "region_conflicts_with_alias", f"the row's region is {region}; the target {eid} is in {tregion}"
    checked = _date(r.get("retrieved"))
    if checked is None:
        return "bad_date", str(r.get("retrieved"))
    if not quote:
        return "no_quote", ""
    if not on:
        return "region_conflicts_with_list", f"{url} is the page of {', '.join(every)}; none is of {tregion}"
    for x in on:  # the list must serve the target's region (rule 5)
        served = ctx.list_regions.get(x, NATIONAL)
        if served not in (NATIONAL, tregion):
            return "region_conflicts_with_list", f"{x} is a list of {served}; the target {eid} is in {tregion}"
    mine = added.get(eid, ())
    if all(x in mine or (x in target["lists"] and x not in weaker) for x in on):
        return "duplicate_membership", f"another row of this file already adds {', '.join(on)} to {eid}"
    new = tuple(x for x in on if x not in target["lists"] and x not in mine)
    upgrade = tuple(x for x in weaker if x not in mine)
    added[eid] = (*mine, *new, *upgrade)
    res.payload.setdefault("provenance", {})["alias"] = dict(used)  # the alias that made it a list line of the target
    res.payload.update(membership={"target": eid, "target_inst_id": to, "lists": new, "upgrade": upgrade},
                       kind=tkind, read_method=rm, region=tregion, url=url, quote=quote, checked_at=checked)
    all_lists = tuple(dict.fromkeys((*target["lists"], *added[eid])))  # the target's lists after the import (rule 6)
    _cap(res, url, tregion, quote, ctx, rm, all_lists, tkind)
    if not new and TRUST_RANK.get(res.level or "", -1) <= min(TRUST_RANK.get(trust[x] or "", -1) for x in upgrade):
        res.bucket, res.level, res.reason, res.detail = "skipped", None, "aliased", to  # capped: no upgrade after all
        res.needs_refetch = False
        res.payload = {"row": r, "provenance": res.payload.get("provenance", {})}
        return None, ""
    res.payload["level_reason"], res.payload["detail_rest"] = res.reason, res.detail
    res.reason = "alias_membership"
    res.detail = membership_detail(res.payload)
    return None, ""


TRUST_RANK = {"unconfirmed": 0, "confirmed": 1, "verified": 2}  # the levels of a loaded row, lowest first


def membership_detail(payload: dict) -> str:
    """The report detail of a list line of an alias (P2-T28): the target and what it adds or upgrades, then the reason
    of its level (kept in `payload["level_reason"]`, so a re-fetch changes it without touching `alias_membership`)."""
    m = payload["membership"]
    what = f"{m['target']} + {', '.join(m['lists'])}" if m["lists"] else m["target"]
    if m.get("upgrade"):
        what += f" (evidence upgraded: {', '.join(m['upgrade'])})"
    return "; ".join(x for x in (what, payload.get("level_reason"), payload.get("detail_rest")) if x)


def _institution_entry(r: dict, rid: str, res: RowResult, ctx: PlanContext, planned: dict[str, str],
                       first: dict[str, tuple[str, str | None]]) -> tuple[str | None, str]:
    fmt = ctx.fmt
    kind = fmt.kind_of_type(_text(r.get("type")))
    if kind is None:
        return "unknown_type", str(r.get("type"))
    url, quote = _text(r.get("source_url")), _text(r.get("source_quote"))
    rm_text = _text(r.get("read_method"))
    rm = fmt.read_method(rm_text)
    if rm is None:
        return "unknown_read_method", str(rm_text)
    if fmt.is_lead_read(rm_text):
        return "non_official_source", "read as a lead"
    prob = _source_problem(url, None, rm, ctx)
    if prob:
        return prob, str(url)
    region, rprob = _region(_text(r.get("region")), kind, ctx)
    if rprob:
        return rprob, str(r.get("region"))
    checked = _date(r.get("retrieved"))
    if checked is None:
        return "bad_date", str(r.get("retrieved"))
    if not quote:
        return "no_quote", ""
    if rid in first and first[rid] != (kind, region):  # a second row of the id (on another list) names the same entity
        return "duplicate_id_conflict", f"{kind}/{region}; an earlier row of the id is {first[rid][0]}/{first[rid][1]}"
    lists: tuple[str, ...] = ()
    eid = f"{KIND_PREFIX[kind]}:{slug(rid)}"
    if kind in ("institution", "campus"):
        on, every = lists_at(ctx, url, region)
        if not every and ctx.require_list:
            return "no_official_list", str(url)
        if every and not on:
            return "region_conflicts_with_list", f"{url} is the page of {', '.join(every)}; none is of {region}"
        lists = on or ("list:not-loaded",)
        # the import keeps the lists the entity already names (R-32): each must serve the row's region, as must its own
        for kept in dict.fromkeys((*ctx.existing_lists(eid), *lists)):
            served = ctx.list_regions.get(kept, NATIONAL)
            if served not in (NATIONAL, region):
                return "region_conflicts_with_list", f"{kept} is a list of {served}; the row's region is {region}"
    parent = None
    if _text(r.get("parent_id")):
        parent = planned.get(_text(r.get("parent_id"))) or ctx.existing_institutions(_text(r.get("parent_id")))
        if parent is None:
            return ("alias_target_not_loaded" if r.get("_alias") else "parent_not_loaded"), str(r.get("parent_id"))
    tz = _text(r.get("timezone"))
    if tz is not None:
        try:
            ZoneInfo(tz)
        except (ZoneInfoNotFoundError, ValueError):
            return "bad_timezone", tz
    ctype = fmt.raw["calendar_types"].get((_text(r.get("type")) or "").lower()) if kind == "calendar" else None
    domains = []
    ou = _text(r.get("official_url"))
    if ou and urlsplit(ou).hostname:
        domains.append(urlsplit(ou).hostname.lower())
    try:
        entry = RegistryEntry(
            entity_id=eid, kind=kind, name=str(r.get("name") or ""), source_url=url,
            checked_at=checked, quote=quote, region=region, institution_type=_text(r.get("type")), parent_id=parent,
            official_domains=tuple(d for d in domains if re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", d)), list_ids=lists,
            attrs={})
    except ValueError as e:
        return "invalid_entry", str(e)
    first.setdefault(rid, (kind, region))
    # the lists the registry names for the entity after the import (R-32): the stored ones, then the row's own
    on_lists = tuple(x for x in dict.fromkeys((*ctx.existing_lists(eid), *lists)) if x != "list:not-loaded")
    res.payload.update(entry=entry, kind=kind, read_method=rm, region=region, url=url, quote=quote, timezone=tz,
                       calendar_type=ctype, lists=on_lists)
    _cap(res, url, region, quote, ctx, rm, on_lists, kind)
    if res.bucket in ("accepted", "unconfirmed"):
        planned[rid] = entry.entity_id
    return None, ""


def plan_programmes_and_facts(batch: Batch, ctx: PlanContext, institutions: list[RowResult],
                              applied: dict[str, dict] | None = None) -> list[RowResult]:
    fmt, applied = ctx.fmt, applied or {}
    abroad = {res.row_id for res in institutions if res.reason in ("out_of_scope", "out_of_scope_region")}
    skipped_programmes: set[str] = set()
    registry_ids = {res.row_id: res.payload["entry"].entity_id for res in institutions
                    if res.bucket in ("accepted", "unconfirmed") and "entry" in res.payload}

    file_regions = {res.payload["entry"].entity_id: res.payload["entry"].region for res in institutions
                    if "entry" in res.payload}
    ctx.region_lookup = lambda rid: file_regions.get(rid) or ctx.existing_region(rid)
    file_meta = {res.payload["entry"].entity_id: {
        "kind": res.payload["kind"], "calendar_type": res.payload.get("calendar_type"),
        "timezone": res.payload.get("timezone"), "parent_id": res.payload["entry"].parent_id}
        for res in institutions if "entry" in res.payload}
    ctx.meta = lambda rid: file_meta.get(rid) or ctx.registry_info(rid)
    file_lists: dict[str, tuple[str, ...]] = {}  # every list the file's rows put an entity on, with its stored ones
    for res in institutions:
        if "entry" in res.payload:
            eid = res.payload["entry"].entity_id
            file_lists[eid] = tuple(dict.fromkeys((*file_lists.get(eid, ()), *res.payload.get("lists", ()))))
    for res in institutions:  # a list line of an aliased id adds its list to the target (P2-T28)
        m = res.payload.get("membership")
        if m and res.bucket in ("accepted", "unconfirmed"):
            base = file_lists.get(m["target"]) or tuple(ctx.existing_lists(m["target"]))
            file_lists[m["target"]] = tuple(dict.fromkeys((*base, *m["lists"])))
    ctx.lists_lookup = lambda rid: file_lists.get(rid) or ctx.existing_lists(rid)

    def inst_registry_id(inst_id: str) -> str | None:
        return registry_ids.get(inst_id) or ctx.existing_institutions(inst_id)

    out: list[RowResult] = []
    programme_refs: set[str] = set()
    seen_keys: set = set()
    seen_programmes: set = set()
    via_alias: list[tuple[RowResult, dict, dict | None]] = []
    for original in batch.sheets.get("Programmes", []):
        r, used = _aliased(original, "inst_id", applied)  # before every other check
        rid = _text(r.get("programme_id")) or ""
        res = RowResult("Programmes", rid, r["_row"], "rejected")
        out.append(res)
        via_alias.append((res, original, used))
        if not rid:
            res.reason = "missing_id"
            continue
        refused = ctx.refused_required.get(_text(original.get("inst_id")) or "")
        if refused:  # a required alias not accepted: never loaded against the id itself (P2-T28)
            res.reason, res.detail = "alias_required_not_accepted", refused
            continue
        status = _text(r.get("claude_status"))
        if status not in fmt.claude_statuses:
            res.reason, res.detail = "bad_status", str(status)
            continue
        if (_text(r.get("inst_id")) or "") in abroad:
            res.bucket, res.reason = "skipped", "entity_out_of_scope"
            skipped_programmes.add(rid)
            continue
        chk = read_checks(r, ctx)
        res.bucket, res.level, res.reason, res.queue_kind = decide(status, chk, True)
        res.detail = "; ".join(chk.notes)
        if res.bucket in ("skipped", "queued"):
            res.level = None
            continue
        problem, detail = _programme_row(r, rid, res, chk, ctx, inst_registry_id, seen_keys, seen_programmes)
        if problem:
            res.bucket, res.level, res.reason, res.detail, res.queue_kind = "rejected", None, problem, detail, None
        elif res.bucket in ("accepted", "unconfirmed"):
            programme_refs.add(rid)  # only a programme that is actually loaded can carry facts
    in_file = _all_programme_ids(batch)
    planned_parent = {res.row_id: res.payload["inst_registry_id"] for res in out if res.sheet == "Programmes"
                      and res.row_id in programme_refs and "inst_registry_id" in res.payload}

    def parent_of(ref: str) -> str | None:  # the institution a programme hangs on: planned in the file, else stored
        return planned_parent.get(ref) or ctx.existing_programme_institution(ref)

    for original in batch.sheets.get("Facts", []):
        r, used = _aliased(original, "entity_id", applied)  # before every other check
        refused = ctx.refused_required.get(_text(original.get("entity_id")) or "")
        if refused and _text(original.get("fact_id")):  # a required alias not accepted (P2-T28)
            out.append(RowResult("Facts", _text(original.get("fact_id")) or "", r["_row"], "rejected",
                                 reason="alias_required_not_accepted", detail=refused))
        else:
            out.append(_fact_row(r, ctx, inst_registry_id, (programme_refs, in_file), seen_keys,
                                 abroad | skipped_programmes, parent_of))
        via_alias.append((out[-1], original, used))
    for res, original, used in via_alias:
        _note_alias(res, original, used)
    return out


def _all_programme_ids(batch: Batch) -> set[str]:
    return {str(r["programme_id"]) for r in batch.sheets.get("Programmes", []) if r.get("programme_id")}


def _programme_row(r, rid, res: RowResult, chk: Checks, ctx: PlanContext, inst_registry_id, seen_keys,
                   seen_programmes) -> tuple[str | None, str]:
    fmt = ctx.fmt
    inst_id = _text(r.get("inst_id"))
    reg_id = inst_registry_id(inst_id or "")
    if reg_id is None:
        return ("alias_target_not_loaded" if r.get("_alias") else "institution_not_loaded"), str(inst_id)
    parent = ctx.meta(reg_id)  # file first, then database; with no meta the kind is unknown and the registry decides
    if parent and parent.get("kind") not in PROGRAMME_PARENTS:
        return "parent_not_institution", f"{inst_id} ({reg_id}) is of kind {parent.get('kind')}"
    url, quote = _text(r.get("source_url")), _text(r.get("quote_verbatim"))
    rm_text = _text(r.get("read_method"))
    rm = fmt.read_method(rm_text) if rm_text else None  # a missing read method is not assumed to be fetch
    if rm_text and rm is None:
        return "unknown_read_method", str(rm_text)
    prob = _source_problem(url, None, rm, ctx)
    if prob:
        return prob, str(url)
    checked = _date(r.get("retrieved"))
    if checked is None:
        return "bad_date", str(r.get("retrieved"))
    if not _text(r.get("programme")):
        return "missing_name", ""
    if not any(_text(r.get(col)) for col in fmt.raw["programme_facts"]):
        return "no_value", ""
    intake_text = _text(r.get("intake"))
    parsed = fmt.intake(intake_text)
    if parsed is None:
        res.bucket, res.level, res.reason, res.queue_kind = "queued", None, "intake_unresolved", "import_dispute"
        res.detail = str(intake_text)
        return None, ""
    term, year = parsed
    category = slug(_text(r.get("seat_category")) or "").replace("-", "_") if _text(r.get("seat_category")) else ""
    facts, keys = [], []
    for col, spec in fmt.raw["programme_facts"].items():
        v = _text(r.get(col))
        if v is None:
            continue
        name = spec["field"] + (f"_{category}" if category and spec.get("by_category") else "")
        value = {"value": v}
        if spec.get("scale") and _text(r.get(spec["scale"])):
            value["scale"] = _text(r.get(spec["scale"]))
        key = ("programme", rid, name, term, year)
        if key in seen_keys or key in keys:
            return "duplicate_key", f"{rid} {name} {intake_text}"
        keys.append(key)
        facts.append({"field": name, "value": value, "fact_class": spec["fact_class"]})
    res.payload = {"row": r, "provenance": chk.provenance, "inst_registry_id": reg_id, "term": term, "year": year,
                   "facts": facts, "read_method": rm, "checked_at": checked, "url": url, "quote": quote,
                   "programme_new": rid not in seen_programmes, "region": ctx.region_lookup(reg_id)}
    seen_programmes.add(rid)
    _cap(res, url, res.payload["region"], quote, ctx, rm, ctx.lists_lookup(reg_id), (parent or {}).get("kind"))
    seen_keys.update(keys)  # registered only once the row has passed every check
    return None, ""


def _fact_row(r, ctx: PlanContext, inst_registry_id, programme_ids: tuple[set[str], set[str]], seen_keys,
              out_of_scope: set[str], parent_of: Callable[[str], str | None] = lambda ref: None) -> RowResult:
    fmt = ctx.fmt
    rid = _text(r.get("fact_id")) or ""
    res = RowResult("Facts", rid, r["_row"], "rejected")
    if not rid:
        res.reason = "missing_id"
        return res
    status = _text(r.get("claude_status"))
    if status not in fmt.claude_statuses:
        res.reason, res.detail = "bad_status", str(status)
        return res
    if (_text(r.get("entity_id")) or "") in out_of_scope:
        res.bucket, res.reason = "skipped", "entity_out_of_scope"
        return res
    chk = read_checks(r, ctx)
    hs_col = (_text(r.get("high_stakes")) or "").upper()
    field_name = _text(r.get("field")) or ""
    cls = _text(r.get("fact_class")) if "fact_class" in r else None
    high = hs_col == "Y" or is_high_stakes(class_of_field(field_name, cls))
    res.bucket, res.level, res.reason, res.queue_kind = decide(status, chk, high)
    res.detail = "; ".join(chk.notes)
    if res.bucket in ("skipped", "queued"):
        res.level = None
        return res
    problem, detail = _fact_checks(r, rid, field_name, high, res, chk, ctx, inst_registry_id, programme_ids, seen_keys,
                                   parent_of)
    if problem:
        res.bucket, res.level, res.reason, res.detail, res.queue_kind = "rejected", None, problem, detail, None
    return res


def _timezone_of(registry_id: str, ctx: PlanContext) -> str | None:
    """The zone of a calendar's dates: its own, else its parent's (a body, board or institution), a few levels up."""
    rid: str | None = registry_id
    for _ in range(4):
        meta = ctx.meta(rid) if rid else None
        if not meta:
            return None
        if meta.get("timezone"):
            return meta["timezone"]
        rid = meta.get("parent_id")
    return None


def _fact_checks(r, rid, field_name, high, res: RowResult, chk: Checks, ctx: PlanContext, inst_registry_id,
                 programme_ids, seen_keys, parent_of) -> tuple[str | None, str]:
    fmt = ctx.fmt
    entity = _text(r.get("entity_id")) or ""
    if not entity:
        return "missing_entity", ""
    if "*" in entity or "," in entity or ";" in entity:
        return "entity_not_single", entity
    if not field_name:
        return "missing_field", ""
    value = _text(r.get("value"))
    if value is None:
        return "no_value", ""
    loaded, in_file = programme_ids
    if r.get("_alias"):  # an alias names an entity of the Institutions sheet, never a programme
        ref = inst_registry_id(entity)
        if ref is None:
            return "alias_target_not_loaded", entity
        scope = "registry"
    elif entity in loaded or (entity not in in_file and ctx.existing_programmes(entity)):
        scope, ref = "programme", entity
    elif entity in in_file:
        return "programme_not_loaded", entity  # a fact is never attached to a programme that was not loaded
    else:
        ref = inst_registry_id(entity)
        if ref is None:
            return ("alias_target_not_loaded" if r.get("_alias") else "entity_unknown"), entity
        scope = "registry"
    url, quote = _text(r.get("source_url")), _text(r.get("quote_verbatim"))
    rm_text = _text(r.get("read_method"))
    rm = fmt.read_method(rm_text)
    if rm is None:
        return "unknown_read_method", str(rm_text)
    if fmt.is_lead_read(rm_text):
        return "non_official_source", "read as a lead"
    prob = _source_problem(url, _text(r.get("source_type")), rm, ctx)
    if prob:
        return prob, str(url)
    checked = _date(r.get("retrieved"))
    if checked is None:
        return "bad_date", str(r.get("retrieved"))
    lang = (_text(r.get("language")) or "").lower() or None
    if lang is not None and not re.fullmatch(r"[a-z]{2,3}", lang):
        return "bad_language", lang
    intake_text = _text(r.get("intake"))
    parsed = fmt.intake(intake_text)
    if parsed is None:
        res.bucket, res.level, res.reason, res.queue_kind = "queued", None, "intake_unresolved", "import_dispute"
        res.detail = str(intake_text)
        return None, ""
    term, year = parsed
    unit = _text(r.get("unit"))
    fact_value: dict = {"value": value, "unit": unit}
    if (unit or "").lower() == "date":  # an ISO date is also kept in the shape the plan compiler reads; other spellings stay text
        try:
            fact_value["date"] = date.fromisoformat(value).isoformat()
        except ValueError:
            pass
    calendar_class = None
    meta = ctx.meta(ref) if scope == "registry" else None
    if meta and meta["kind"] == "calendar":  # a date of an official calendar (P2-T11): its field, date and zone are checked
        ctype = calendar_types().get(meta["calendar_type"] or "")
        if ctype is None:
            return "calendar_without_type", ref
        if field_name not in ctype.fields:
            return "field_not_in_calendar", f"'{field_name}' is not a date of a {ctype.key} calendar"
        try:
            day = date.fromisoformat(value)
        except ValueError:
            return "not_a_date", value
        tz = _timezone_of(ref, ctx)
        if tz is None:
            return "no_timezone", ref
        fact_value, calendar_class = {"date": day.isoformat(), "tz": tz}, ctype.fields[field_name]
    key = (scope, ref, field_name, term, year)
    if key in seen_keys:
        return "duplicate_key", f"{entity} {field_name} {intake_text}"
    res.payload = {"row": r, "provenance": chk.provenance, "scope": scope, "ref": ref, "field": field_name,
                   "value": fact_value, "quote": quote or "", "url": url, "term": term, "calendar": calendar_class,
                   "year": year, "read_method": rm, "language": lang, "checked_at": checked, "high_stakes": high,
                   "source_type": _text(r.get("source_type"))}
    # the entity whose region and lists judge the source: the fact's own, or the institution its programme hangs on
    owner = ref if scope == "registry" else parent_of(ref)
    region = ctx.region_lookup(owner) if owner else None
    res.payload["region"] = region
    owner_kind = (ctx.meta(owner) or {}).get("kind") if owner else None  # file first, then database; None: unknown
    _cap(res, url, region, quote, ctx, rm, ctx.lists_lookup(owner) if owner else (), owner_kind)
    seen_keys.add(key)  # registered only once the row has passed every check
    return None, ""


def plan_batch(batch: Batch, ctx: PlanContext) -> list[RowResult]:
    """Every row of every sheet with its decision, institutions first (programmes and facts need them)."""
    ctx.batch_sha = batch.sha256
    bind(ctx.aliases, batch.sha256, batch.path.name)  # an alias file for another file is refused, whole
    alias_rows, applied = resolve_aliases(ctx)
    ctx.applied_aliases = applied
    inst = plan_institutions(batch, ctx, applied)
    return alias_rows + inst + plan_programmes_and_facts(batch, ctx, inst, applied)


def summarise(results: list[RowResult]) -> dict[str, dict[str, int]]:
    """Counts per sheet and bucket, plus the loaded rows split by level."""
    out: dict[str, dict[str, int]] = {}
    for r in results:
        s = out.setdefault(r.sheet, dict.fromkeys(BUCKETS, 0))
        s[r.bucket] += 1
        if r.bucket == "accepted" and r.level:
            s[r.level] = s.get(r.level, 0) + 1
        if r.needs_refetch:
            s["needs_refetch"] = s.get("needs_refetch", 0) + 1
    return out
