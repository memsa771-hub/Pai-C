"""Decides, for every row of a batch, what happens to it (P2 spec §4.6 "Status mapping", P2-D16, P2-D16a; master R-68).

Pure: it reads nothing from the database and writes nothing. The same plan is what a dry run reports and what the import
then loads, so the two never differ. Buckets:

- `accepted`      loaded as `verified` or `confirmed` (see `level`; `needs_refetch` rows wait for the quote match);
- `unconfirmed`   loaded as `unconfirmed`, shown as "not confirmed yet";
- `queued`        not loaded; a review item is opened (`import_dispute`, `collect`);
- `rejected`      not loaded; listed in the import report with the reason;
- `skipped`       nothing to load by design (lead, history, searched-and-not-found, out of scope).
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import urlsplit

from app.os.knowledge.fact_classes import fact_class as class_of_field
from app.os.knowledge.fact_classes import is_high_stakes
from app.os.knowledge.regions import UnknownRegion, normalise_region
from app.os.knowledge.sheets.format import Format, load_format
from app.os.knowledge.sheets.reader import Batch
from app.os.registry.model import KIND_PREFIX, REGION_REQUIRED, RegistryEntry, slug

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
    family: str = ""  # the batch's family, for the allow-list scope (data of the batch, never guessed)
    attested: Callable[[str, str], bool] | None = None  # (reviewer ref, batch ref) -> bool; reviewer mode (T5)
    official: Callable[[str, Scope], bool] | None = None  # allow-list lookup (T3); None = not checked
    list_urls: dict[str, str] = field(default_factory=dict)  # official list URL -> list entity id
    existing_institutions: Callable[[str], str | None] = lambda inst_id: None  # inst_id -> registry id already loaded
    existing_programmes: Callable[[str], bool] = lambda ref: False
    require_list: bool = True  # False only for a dry run that asks "what if every list were loaded"
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


def read_checks(row: dict, ctx: PlanContext) -> Checks:
    fmt = ctx.fmt
    c1 = (_text(row.get("checker1_result")) or "").lower() or None
    c2 = fmt.check2_values.get((_text(row.get("checker2_approved")) or "").lower())
    n1, n2 = _text(row.get("checker1_name")), _text(row.get("checker2_name"))
    notes: list[str] = []
    if c1 is not None and c1 not in fmt.check1_results:
        notes.append(f"checker1_result '{c1}' is not allowed")
        c1 = None
    if ctx.mode == OWNER_ACCEPTED:
        r1, r2 = fmt.owner_accepted_ref(1, n1), fmt.owner_accepted_ref(2, n2)
        if c1 is not None and r1 is None:
            notes.append("checker 1 is not a check the owner accepted")
            c1 = None
        if c2 is not None and r2 is None:
            notes.append("checker 2 is not a check the owner accepted")
            c2 = None
        prov = {"checker1": r1, "checker2": r2, "checker1_name": n1, "checker2_name": n2}
    else:
        ok = lambda n: bool(n) and ctx.attested is not None and ctx.attested(n, ctx.batch_ref)  # noqa: E731
        if c1 is not None and not ok(n1):
            notes.append(f"checker 1 '{n1}' has not attested batch {ctx.batch_ref}")
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
    if status == "not_readable" or chk.c1 == "not_readable":
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


def _scope(region: str | None, ctx: PlanContext) -> Scope:
    return Scope(region=region or "", family=ctx.family)


def _cap(result: RowResult, url: str, region: str | None, quote: str | None, ctx: PlanContext,
         read_method: str | None) -> None:
    """Things that stop a row above `unconfirmed`: no quote, off the allow-list, a model or OCR reading."""
    if result.bucket not in ("accepted",):
        return
    if not quote:
        _lower(result, "no_quote")
    elif ctx.official is not None and not ctx.official(url, _scope(region, ctx)):
        _lower(result, "source_not_on_allow_list")
    elif read_method in ctx.fmt.needs_refetch:
        result.needs_refetch = True


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


def plan_institutions(batch: Batch, ctx: PlanContext) -> list[RowResult]:
    fmt, out, seen = ctx.fmt, [], set()
    for r in batch.sheets["Institutions"]:
        rid = _text(r.get("inst_id")) or ""
        res = RowResult("Institutions", rid, r["_row"], "rejected")
        out.append(res)
        if not rid:
            res.reason = "missing_id"
            continue
        if rid in seen:
            res.reason = "duplicate_id"
            continue
        seen.add(rid)
        status = _text(r.get("claude_status"))
        if status not in fmt.claude_statuses:
            res.reason, res.detail = "bad_status", str(status)
            continue
        if (_text(r.get("in_scope")) or "yes").lower() in ("no", "n", "false"):
            res.bucket, res.reason = "skipped", "out_of_scope"
            continue
        chk = read_checks(r, ctx)
        res.bucket, res.level, res.reason, res.queue_kind = decide(status, chk, False)
        res.detail = "; ".join(chk.notes)
        res.payload = {"row": r, "provenance": chk.provenance}
        if res.bucket in ("skipped", "queued"):
            res.level = None
            continue
        problem, detail = _institution_entry(r, rid, res, ctx)
        if problem:
            res.bucket, res.level, res.reason, res.detail, res.queue_kind = "rejected", None, problem, detail, None
    return out


def _institution_entry(r: dict, rid: str, res: RowResult, ctx: PlanContext) -> tuple[str | None, str]:
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
    lists: tuple[str, ...] = ()
    if kind in ("institution", "campus"):
        lid = ctx.list_urls.get(norm_url(url or ""))
        if lid is None and ctx.require_list:
            return "no_official_list", str(url)
        lists = (lid or "list:not-loaded",)
    domains = []
    ou = _text(r.get("official_url"))
    if ou and urlsplit(ou).hostname:
        domains.append(urlsplit(ou).hostname.lower())
    try:
        entry = RegistryEntry(
            entity_id=f"{KIND_PREFIX[kind]}:{slug(rid)}", kind=kind, name=str(r.get("name") or ""), source_url=url,
            checked_at=checked, quote=quote, region=region, institution_type=_text(r.get("type")),
            official_domains=tuple(d for d in domains if re.match(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$", d)), list_ids=lists,
            attrs={})
    except ValueError as e:
        return "invalid_entry", str(e)
    res.payload.update(entry=entry, kind=kind, read_method=rm, region=region, url=url, quote=quote)
    _cap(res, url, region, quote, ctx, rm)
    return None, ""


def _fact_key_seen(seen: set, key: tuple) -> bool:
    if key in seen:
        return True
    seen.add(key)
    return False


def plan_programmes_and_facts(batch: Batch, ctx: PlanContext, institutions: list[RowResult]) -> list[RowResult]:
    fmt = ctx.fmt
    registry_ids = {res.row_id: res.payload["entry"].entity_id for res in institutions
                    if res.bucket in ("accepted", "unconfirmed") and "entry" in res.payload}

    def inst_registry_id(inst_id: str) -> str | None:
        return registry_ids.get(inst_id) or ctx.existing_institutions(inst_id)

    out: list[RowResult] = []
    programme_refs: set[str] = set()
    seen_keys: set = set()
    seen_programmes: set = set()
    for r in batch.sheets.get("Programmes", []):
        rid = _text(r.get("programme_id")) or ""
        res = RowResult("Programmes", rid, r["_row"], "rejected")
        out.append(res)
        if not rid:
            res.reason = "missing_id"
            continue
        status = _text(r.get("claude_status"))
        if status not in fmt.claude_statuses:
            res.reason, res.detail = "bad_status", str(status)
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
        else:
            programme_refs.add(rid)
    for r in batch.sheets.get("Facts", []):
        out.append(_fact_row(r, ctx, inst_registry_id, programme_refs | _all_programme_ids(batch), seen_keys))
    return out


def _all_programme_ids(batch: Batch) -> set[str]:
    return {str(r["programme_id"]) for r in batch.sheets.get("Programmes", []) if r.get("programme_id")}


def _programme_row(r, rid, res: RowResult, chk: Checks, ctx: PlanContext, inst_registry_id, seen_keys,
                   seen_programmes) -> tuple[str | None, str]:
    fmt = ctx.fmt
    inst_id = _text(r.get("inst_id"))
    reg_id = inst_registry_id(inst_id or "")
    if reg_id is None:
        return "institution_not_loaded", str(inst_id)
    url, quote = _text(r.get("source_url")), _text(r.get("quote_verbatim"))
    rm_text = _text(r.get("read_method"))
    rm = fmt.read_method(rm_text) if rm_text else "fetch"
    if rm is None:
        return "unknown_read_method", str(rm_text)
    prob = _source_problem(url, None, rm, ctx)
    if prob:
        return prob, str(url)
    checked = _date(r.get("retrieved"))
    if checked is None:
        return "bad_date", str(r.get("retrieved"))
    if not _text(r.get("programme")):
        return "missing_name", ""
    intake_text = _text(r.get("intake"))
    parsed = fmt.intake(intake_text)
    if parsed is None:
        res.bucket, res.level, res.reason, res.queue_kind = "queued", None, "intake_unresolved", "import_dispute"
        res.detail = str(intake_text)
        return None, ""
    term, year = parsed
    category = slug(_text(r.get("seat_category")) or "").replace("-", "_") if _text(r.get("seat_category")) else ""
    facts = []
    for col, spec in fmt.raw["programme_facts"].items():
        v = _text(r.get(col))
        if v is None:
            continue
        name = spec["field"] + (f"_{category}" if category and spec.get("by_category") else "")
        value = {"value": v}
        if spec.get("scale") and _text(r.get(spec["scale"])):
            value["scale"] = _text(r.get(spec["scale"]))
        key = ("programme", rid, name, term, year)
        if key in seen_keys:
            return "duplicate_key", f"{rid} {name} {intake_text}"
        seen_keys.add(key)
        facts.append({"field": name, "value": value, "fact_class": spec["fact_class"]})
    res.payload = {"row": r, "provenance": chk.provenance, "inst_registry_id": reg_id, "term": term, "year": year,
                   "facts": facts, "read_method": rm, "checked_at": checked, "url": url, "quote": quote,
                   "programme_new": rid not in seen_programmes}
    seen_programmes.add(rid)
    _cap(res, url, None, quote, ctx, rm)
    return None, ""


def _fact_row(r, ctx: PlanContext, inst_registry_id, programme_ids: set[str], seen_keys) -> RowResult:
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
    problem, detail = _fact_checks(r, rid, field_name, high, res, chk, ctx, inst_registry_id, programme_ids, seen_keys)
    if problem:
        res.bucket, res.level, res.reason, res.detail, res.queue_kind = "rejected", None, problem, detail, None
    return res


def _fact_checks(r, rid, field_name, high, res: RowResult, chk: Checks, ctx: PlanContext, inst_registry_id,
                 programme_ids, seen_keys) -> tuple[str | None, str]:
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
    if entity in programme_ids or ctx.existing_programmes(entity):
        scope, ref = "programme", entity
    else:
        ref = inst_registry_id(entity)
        if ref is None:
            return "entity_unknown", entity
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
    key = (scope, ref, field_name, term, year)
    if _fact_key_seen(seen_keys, key):
        return "duplicate_key", f"{entity} {field_name} {intake_text}"
    unit = _text(r.get("unit"))
    res.payload = {"row": r, "provenance": chk.provenance, "scope": scope, "ref": ref, "field": field_name,
                   "value": {"value": value, "unit": unit}, "quote": quote or "", "url": url, "term": term,
                   "year": year, "read_method": rm, "language": lang, "checked_at": checked, "high_stakes": high,
                   "source_type": _text(r.get("source_type"))}
    _cap(res, url, None, quote, ctx, rm)
    return None, ""


def plan_batch(batch: Batch, ctx: PlanContext) -> list[RowResult]:
    """Every row of every sheet with its decision, institutions first (programmes and facts need them)."""
    inst = plan_institutions(batch, ctx)
    return inst + plan_programmes_and_facts(batch, ctx, inst)


def summarise(results: list[RowResult]) -> dict[str, dict[str, int]]:
    """Counts per sheet and bucket, plus the loaded rows split by level."""
    out: dict[str, dict[str, int]] = {}
    for r in results:
        s = out.setdefault(r.sheet, dict.fromkeys(BUCKETS, 0))
        s[r.bucket] += 1
        if r.bucket in ("accepted", "unconfirmed") and r.level:
            s[r.level] = s.get(r.level, 0) + 1
        if r.needs_refetch:
            s["needs_refetch"] = s.get("needs_refetch", 0) + 1
    return out
