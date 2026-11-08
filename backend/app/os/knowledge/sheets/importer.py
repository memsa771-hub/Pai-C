"""Imports a returned batch into Knowledge and the registry (P2 spec §4.6; master R-68). The order is: read and map the
file, plan every row (plan.py), optionally re-fetch quotes, load what passed through the stores' `record` paths, queue
what needs a person, log the import, write the report beside the file.

Every revision an import writes carries `cause_ref = import-<id>` so undo can find it. `verified` is reached only through
`set_status(..., cause="review")`, as everywhere (T1); the owner-accepted mode records who accepted it (P2-D16a)."""

import csv
import io
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine

from app.os.knowledge.port import Fact
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.sheets.format import Format, load_format
from app.os.knowledge.sheets.importlog import AlreadyImported, ImportLog, cause_ref
from app.os.knowledge.sheets.plan import (
    OWNER_ACCEPTED,
    REVIEWERS,
    PlanContext,
    RowResult,
    norm_url,
    plan_batch,
    summarise,
)
from app.os.knowledge.sheets.ports import Disputes, Fetcher
from app.os.knowledge.sheets.reader import Batch, read_batch
from app.os.knowledge.sheets.safe import safe_cell
from app.os.knowledge.store import SqlKnowledge
from app.os.registry.calendars import record_calendar, record_calendar_date
from app.os.registry.model import KIND_PREFIX, slug
from app.os.registry.store import RegistryStore

__all__ = ["AlreadyImported", "ImportDeps", "ImportRefused", "ImportResult", "build_context", "plan_file", "plan_hook", "run_import",
           "wire_other_tasks", "write_report"]
REPORT_COLUMNS = ("sheet", "row_id", "source_row", "bucket", "level", "reason", "detail")


@dataclass
class ImportDeps:
    engine: Engine
    tenant_id: str
    knowledge: SqlKnowledge
    registry: RegistryStore
    programmes: ProgrammeStore
    fetcher: Fetcher | None = None
    disputes: Disputes | None = None
    attested: Any = None  # (reviewer ref, batch ref) -> bool  (ReviewQueue.attested)
    official: Any = None  # (url, scope) -> bool  (allow-list; None = not checked)
    # (scope, ref, field, fact id, status, intake year) -> None, called after each fact is written (and committed), so the
    # plans that use it follow it (row 6.10). `plan_hook(plans, kernel)` builds it from the plan service.
    on_fact_change: Any = None
    hook_errors: list = field(default_factory=list)  # plan revisions that failed after a fact was stored (per run)


@dataclass
class ImportResult:
    import_id: int | None
    dry_run: bool
    rows: list[RowResult]
    counts: dict[str, dict[str, int]]
    report_path: Path | None = None
    programmes_created: list[str] = field(default_factory=list)
    queued_items: int = 0
    layouts: dict[str, str] = field(default_factory=dict)
    hook_errors: list[str] = field(default_factory=list)


def _info(e) -> dict | None:
    """What the plan needs of a stored entity for a calendar date: its kind, calendar type, zone and parent."""
    if e is None:
        return None
    return {"kind": e.kind, "calendar_type": e.attrs.get("calendar_type"), "timezone": e.attrs.get("timezone"),
            "parent_id": e.parent_id}


def _registry_lookup(registry: RegistryStore):
    def lookup(inst_id: str) -> str | None:
        for prefix in KIND_PREFIX.values():
            rid = f"{prefix}:{slug(inst_id)}"
            if registry.get(rid) is not None:
                return rid
        return None
    return lookup


class ImportRefused(ValueError):
    """The import cannot run safely as set up (a port it needs is not connected). Nothing is logged or loaded."""


def build_context(deps: ImportDeps | None, *, country: str, mode: str, batch_ref: str, family: str,
                  list_urls: dict[str, str] | None = None, require_list: bool = True,
                  decision_ref: str | None = None, fmt: Format | None = None) -> PlanContext:
    from app.os.knowledge.regions import countries

    if country not in countries():
        raise ValueError(f"no region vocabulary for country '{country}' (known: {countries()})")
    ctx = PlanContext(country=country, mode=mode, batch_ref=batch_ref, family=family, require_list=require_list,
                      decision_ref=decision_ref, fmt=fmt or load_format())
    urls: dict[str, str] = dict(list_urls or {})
    if deps is not None:
        for e in deps.registry.list(kind="official_list", limit=100_000):
            urls.setdefault(norm_url(e.source_url), e.entity_id)
        ctx.attested, ctx.official = deps.attested, deps.official
        ctx.cap_without_allow_list = deps.official is None  # no allow-list connected: nothing above `unconfirmed`
        ctx.existing_institutions = _registry_lookup(deps.registry)
        ctx.existing_programmes = lambda ref: deps.programmes.get(ref) is not None
        ctx.existing_region = lambda rid: getattr(deps.registry.get(rid), "region", None)
        ctx.registry_info = lambda rid: _info(deps.registry.get(rid))
    ctx.list_urls = urls
    return ctx


def plan_hook(plans, kernel):
    """The `on_fact_change` hook for the plan service: completes the waiting confirm tasks of a confirmed fact and revises
    the plans that use it (knowledge.changes.after_fact_change)."""
    from app.os.knowledge.changes import after_fact_change

    def hook(scope: str, ref: str, field: str, fact_id: int, status: str, intake_year: int) -> None:
        after_fact_change(plans, kernel, scope, ref, field, fact_id, status, intake_year,
                          complete=status in ("confirmed", "verified"))

    return hook


def wire_other_tasks(deps: ImportDeps) -> ImportDeps:
    """Connects the review queue (T5: disputes and attestation) and the allow-list (T3) when their code is present."""
    try:
        from app.os.knowledge.review.queue import ReviewQueue

        queue = ReviewQueue(deps.engine, deps.tenant_id, deps.knowledge)
        deps.disputes, deps.attested = queue, queue.attested
    except ImportError:
        pass
    try:
        from app.os.knowledge.sources.allowlist import SourceDomains

        domains = SourceDomains(deps.engine, deps.tenant_id)
        deps.official = lambda url, scope: domains.is_listed(urlsplit(url).hostname or "", scope)
    except ImportError:
        pass
    return deps


def plan_file(path: Path, ctx: PlanContext, fmt: Format | None = None) -> tuple[Batch, list[RowResult]]:
    """Read and plan only: the dry run. Touches no database."""
    batch = read_batch(path, fmt or load_format())
    return batch, plan_batch(batch, ctx)


def _jsonable(o: Any) -> Any:
    if isinstance(o, datetime):
        return o.isoformat()
    return str(o)


def report_text(results: list[RowResult]) -> str:
    """Every row with its fate, as CSV (P2 spec §4.6 step 4): nothing fails silently. Cells that start like a formula
    are neutralised (the report is opened in a spreadsheet)."""
    buf = io.StringIO(newline="")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(REPORT_COLUMNS)
    for r in results:
        w.writerow([safe_cell(c) for c in (r.sheet, r.row_id, r.src_row, r.bucket, r.level or "", r.reason, r.detail)])
    return buf.getvalue()


def write_report(results: list[RowResult], path: Path) -> Path:
    path.write_text(report_text(results), encoding="utf-8", newline="")
    return path


def _evidence(res: RowResult, mode: str, decision_ref: str | None, import_id: int, actor: str) -> list[dict]:
    prov = dict(res.payload.get("provenance") or {})
    ev = {"import_id": import_id, "mode": mode, "sheet": res.sheet, "row": res.row_id, "source_row": res.src_row,
          "level": res.level, "reason": res.reason, **prov}
    if mode == OWNER_ACCEPTED:
        ev.update(accepted_by="owner", decision_ref=decision_ref,
                  note="the developers reviewed the batches; both checks are AI checks (P2-D16a)")
    return [ev]


def _apply_refetch(results: list[RowResult], refetcher) -> None:
    """R-68: model- and OCR-read rows are confirmed only if the quote matches on the re-fetched page; an unconfirmed
    row with a quote is promoted when it matches. A mismatch never raises a level."""
    for r in results:
        p = r.payload
        if r.bucket not in ("accepted", "unconfirmed") or not p.get("url") or not p.get("quote"):
            continue
        promotable = r.bucket == "unconfirmed" and r.reason == "check_unclear_or_missing"
        if not (r.needs_refetch or promotable):
            continue
        out = refetcher.check(p["url"], p["quote"], p.get("region"))
        if r.needs_refetch:
            r.needs_refetch = False
            if not out.matched:
                r.bucket, r.level, r.reason, r.detail = "unconfirmed", "unconfirmed", out.reason, p["url"]
        elif out.matched:
            r.bucket, r.level, r.reason = "accepted", "confirmed", "quote_matched_on_refetch"


def _queue(deps: ImportDeps, res: RowResult, sha: str, batch_ref: str) -> bool:
    if deps.disputes is None or res.bucket != "queued":
        return False
    row = {k: v for k, v in (res.payload.get("row") or {}).items() if v is not None}
    deps.disputes.open_item(
        res.queue_kind or "import_dispute", dedupe_key=f"import:{sha[:16]}:{res.sheet}:{res.row_id}:{res.src_row}",
        subject=res.row_id, summary=f"{res.sheet} {res.row_id}: {res.reason}",
        payload=json.loads(json.dumps({"sheet": res.sheet, "reason": res.reason, "detail": res.detail, "row": row},
                                      default=_jsonable)), batch_ref=batch_ref, opened_by="import")
    return True


def _write_fact(deps: ImportDeps, res: RowResult, spec: dict, import_id: int, mode: str, decision_ref: str | None,
                actor: str) -> int:
    p = res.payload
    status = "confirmed" if res.level in ("verified", "confirmed") else "unconfirmed"
    quote = spec.get("quote", p.get("quote")) or ""
    cref = cause_ref(import_id)
    evidence = _evidence(res, mode, decision_ref, import_id, actor)
    if p.get("calendar"):  # a date of an official calendar: through the calendar's own path, which checks its type
        from datetime import date as _date

        fid = record_calendar_date(
            deps.registry, deps.knowledge, spec["ref"], spec["field"], _date.fromisoformat(spec["value"]["date"]),
            tz=spec["value"]["tz"], url=p.get("url") or "", quote=quote, checked_at=p["checked_at"],
            intake_year=p["year"], intake_term=p["term"], status=status, cause="import", cause_ref=cref, actor=actor,
            read_method=p.get("read_method"), language=p.get("language"), evidence=evidence)
    else:
        fact = Fact(value=spec["value"], quote=quote, url=p.get("url") or "", checked_at=p["checked_at"],
                    intake_year=p["year"], status=status, intake_term=p["term"], fact_class=spec.get("fact_class"),
                    read_method=p.get("read_method"), language=p.get("language"),
                    conflict_note=("conflict: " + (res.detail or res.reason)) if res.reason == "conflict" else None)
        fid = deps.knowledge.upsert(spec["scope"], spec["ref"], spec["field"], fact, source="manual",
                                    evidence=evidence, cause="import", cause_ref=cref, actor=actor)
    if res.level == "verified":
        who = f"owner-accepted:{decision_ref}" if mode == OWNER_ACCEPTED else actor
        deps.knowledge.set_status(fid, "verified", cause="review", cause_ref=cref, actor=who)
    if deps.on_fact_change is not None:  # after the commit: the plans that use the fact follow it (row 6.10)
        try:
            deps.on_fact_change(spec["scope"], spec["ref"], spec["field"], fid, res.level or status, p["year"])
        except Exception as e:  # noqa: BLE001  (the fact is stored; a plan that cannot follow is reported, not hidden)
            deps.hook_errors.append(f"{spec['scope']}:{spec['ref']}:{spec['field']}: {type(e).__name__}: {e}")
    return fid


def run_import(path: Path, deps: ImportDeps, *, mode: str, actor: str, country: str, decision_ref: str | None = None,
               batch_ref: str | None = None, family: str = "", route_key: str = "registry",
               report_path: Path | None = None, note_actor: str | None = None,
               fmt: Format | None = None) -> ImportResult:
    """The real import. Refuses: an owner-accepted import without its decision reference; a file already imported
    (done, or failed and not undone); rows that need a review item when no review queue is connected. With no allow-list
    connected, no row goes above `unconfirmed`. `actor` is the identity that runs it, `note_actor` a typed name."""
    if mode not in (OWNER_ACCEPTED, REVIEWERS):
        raise ValueError(f"unknown import mode '{mode}'")
    if mode == OWNER_ACCEPTED and not (decision_ref or "").strip():
        raise ValueError("the owner-accepted import needs the owner's decision reference (--owner-accepted <ref>)")
    path = Path(path)
    batch_ref = batch_ref or path.stem
    ctx = build_context(deps, country=country, mode=mode, batch_ref=batch_ref, family=family,
                        decision_ref=decision_ref, fmt=fmt)
    batch, results = plan_file(path, ctx, fmt)
    n_queued = sum(1 for r in results if r.bucket == "queued")
    if n_queued and deps.disputes is None:
        raise ImportRefused(f"{n_queued} rows need a review item but the review queue is not connected; "
                            "nothing was imported")
    log = ImportLog(deps.engine, deps.tenant_id)
    import_id = log.start(file_name=path.name, sha256=batch.sha256, mode=mode, decision_ref=decision_ref,
                          batch_ref=batch_ref, actor=actor, note_actor=note_actor)
    created: list[str] = []
    queued = 0
    deps.hook_errors = []
    try:
        from app.os.knowledge.sheets.refetch import Refetcher

        _apply_refetch(results, Refetcher(deps.fetcher, family))
        for r in results:  # a model/OCR row nobody could re-fetch stays unconfirmed (R-68)
            if r.needs_refetch and r.bucket == "accepted":
                r.bucket, r.level, r.reason = "unconfirmed", "unconfirmed", "refetch_not_run"
                r.needs_refetch = False
        cref = cause_ref(import_id)
        for r in results:
            if r.bucket == "queued":
                queued += _queue(deps, r, batch.sha256, batch_ref)
            elif r.bucket in ("accepted", "unconfirmed") and r.payload:
                if r.sheet == "Institutions":
                    _load_institution(deps, r, import_id, mode, decision_ref, actor, cref)
                elif r.sheet == "Programmes":
                    _load_programme(deps, r, import_id, mode, decision_ref, actor, cref, route_key, created)
                else:
                    r.payload["fid"] = _write_fact(deps, r, r.payload, import_id, mode, decision_ref, actor)
                if r.queue_kind == "conflict" and deps.disputes is not None and r.payload.get("fid"):
                    deps.disputes.open_item("conflict", dedupe_key=f"import:{batch.sha256[:16]}:{r.sheet}:{r.row_id}",
                                            fact_id=r.payload["fid"], summary=f"{r.row_id}: sources disagree",
                                            batch_ref=batch_ref, opened_by="import")
                    queued += 1
        counts = summarise(results)
        text = report_text(results)
        default_report = path / "import-report.csv" if path.is_dir() else path.with_name(path.stem + ".import-report.csv")
        try:
            rp = write_report(results, report_path or default_report)
        except OSError:  # the copy beside the file is a convenience; the log keeps the report
            rp = None
        problems = (f"{len(deps.hook_errors)} plan revisions failed after their fact was stored: "
                    + "; ".join(deps.hook_errors))[:2000] if deps.hook_errors else None
        log.finish(import_id, status="done", counts=counts, programmes_created=created,
                   report_path=str(rp) if rp else None, report_csv=text, error=problems)
    except Exception as e:
        log.finish(import_id, status="failed", error=f"{type(e).__name__}: {e}"[:2000], programmes_created=created)
        raise
    return ImportResult(import_id, False, results, counts, rp, created, queued, batch.layouts,
                        list(deps.hook_errors))


def _load_institution(deps: ImportDeps, r: RowResult, import_id: int, mode: str, decision_ref: str | None,
                      actor: str, cref: str) -> None:
    row, entry = r.payload["row"], r.payload["entry"]
    attrs = {k: row[k] for k in ("city", "sector", "discipline", "chartered_by", "official_url", "claude_note")
             if row.get(k) is not None}
    attrs.update(inst_id=r.row_id, trust=r.level, import_id=import_id,
                 provenance=_evidence(r, mode, decision_ref, import_id, actor)[0])
    if r.payload.get("timezone"):
        attrs["timezone"] = r.payload["timezone"]
    if entry.kind == "calendar":  # a calendar is recorded with its type; its dates come as facts (record_calendar_date)
        record_calendar(deps.registry, replace(entry, attrs=attrs), r.payload["calendar_type"], cause="import",
                        cause_ref=cref, actor=actor)
        return
    deps.registry.record(replace(entry, attrs=attrs), cause="import", cause_ref=cref, actor=actor)


def _load_programme(deps: ImportDeps, r: RowResult, import_id: int, mode: str, decision_ref: str | None, actor: str,
                    cref: str, route_key: str, created: list[str]) -> None:
    p, row = r.payload, r.payload["row"]
    ref = r.row_id
    inst = deps.registry.get(p["inst_registry_id"])
    if deps.programmes.get(ref) is None:
        https = tuple(u for u in (p.get("url"),) if u and u.startswith("https://"))
        deps.programmes.upsert(Programme(ref=ref, route_key=route_key, university=inst.name if inst else "",
                                         name=str(row["programme"]), aliases=(), start_urls=https,
                                         official_domains=(), notes=row.get("campus")))
        created.append(ref)
    place = {k: v for k, v in (("level", row.get("level")), ("field", row.get("field")),
                               ("region", inst.region if inst else None)) if v is not None}
    deps.registry.link_programme(ref, institution_id=p["inst_registry_id"], cause="import", cause_ref=cref,
                                 actor=actor, **place)
    for f in p["facts"]:
        _write_fact(deps, r, {**f, "scope": "programme", "ref": ref}, import_id, mode, decision_ref, actor)
