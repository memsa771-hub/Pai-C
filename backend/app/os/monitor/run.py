"""The daily monitoring job `os.monitor` (P2 spec §4.7, P2-D20, P2-D21; R-27; row 6.24).

For each region and family inside its notice window: group the confirmed and verified facts of the window's intake by
source URL, read each page again, and check each fact's quote on the new page. A fact goes back to `unconfirmed` (marker
`monitor`) only when its evidence is missing on two separate runs: the quote is gone from the page, or the page is gone
(404 or 410). The plans that use it are revised (the steps it dates wait, `fact_rechecking`) and a `change` item opens.

A page that cannot be trusted changes nothing and is not kept as the last clean snapshot: one that cannot be read now
(a timeout, a server error, a block), one that shrank by more than the configured share, or one on which none of the quotes
of the facts it backs is found. Facts only change through the Knowledge store; plans only through `after_change`."""

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Engine, delete, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import models
from app.os.knowledge.port import Fact
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.knowledge.research.pages import PageGateway
from app.os.knowledge.research.text import normalise
from app.os.knowledge.research.trust import quote_on_page
from app.os.knowledge.review.queue import ReviewQueue
from app.os.knowledge.sources.allowlist import Scope
from app.os.knowledge.sources.snapshots import SnapshotStore, text_hash
from app.os.knowledge.store import SqlKnowledge, StaleFact, fact_digest
from app.os.monitor.config import MonitorConfig, load_config
from app.os.monitor.windows import Window, active_windows

log = logging.getLogger(__name__)
K, RUNS, SEEN = models.knowledge_facts, models.monitor_runs, models.monitor_seen
# after_change(scope, ref, field, fact_id, status, intake_year): revises the plans that use the fact
AfterChange = Callable[[str, str, str, int, str, int], None]
_GUARDED = ("integrity:", "suspect_domain", "tls_", "insecure_scheme", "redirect_not_official")
COUNTS = ("windows", "urls", "facts", "taken_back", "seen_once", "unreadable", "guarded", "page_changed")


@dataclass(frozen=True)
class _Source:
    fact_id: int
    scope: str
    ref: str
    field: str
    year: int
    fact: Fact
    domains: tuple[str, ...]


def _facts_by_url(engine: Engine, tenant_id: str, w: Window, programmes: list[Programme],
                  cfg: MonitorConfig) -> dict[str, list[_Source]]:
    mine = {p.ref: p for p in programmes if p.region == w.region and p.family == w.family and p.status == "active"}
    if not mine:
        return {}
    with engine.connect() as conn:
        rows = conn.execute(select(K).where(
            K.c.tenant_id == tenant_id, K.c.scope == "programme", K.c.ref.in_(list(mine)),
            K.c.intake_year == w.year, K.c.intake_term.in_([w.term, ""]), K.c.status.in_(cfg.monitored_statuses),
            K.c.url != "").order_by(K.c.id)).all()
    out: dict[str, list[_Source]] = defaultdict(list)
    for r in rows:
        fact = Fact(value=r.value, quote=r.quote, url=r.url, checked_at=r.checked_at, intake_year=r.intake_year,
                    status=r.status, conflict_note=r.conflict_note, id=r.id, intake_term=r.intake_term,
                    owner_ref=r.owner_ref, fact_class=r.fact_class, read_method=r.read_method, language=r.language,
                    recheck=r.recheck_reason)
        out[r.url].append(_Source(r.id, r.scope, r.ref, r.field, r.intake_year, fact, mine[r.ref].official_domains))
    return out


def _lock_run(conn, tenant_id: str, today: date):
    """The day's run row, locked for as long as `conn`'s transaction lasts; None if another worker holds it."""
    return conn.execute(select(RUNS).where(RUNS.c.tenant_id == tenant_id, RUNS.c.run_date == today)
                        .with_for_update(skip_locked=True)).first()


def run(engine: Engine, tenant_id: str, today: date, now: datetime, *, gateway: PageGateway, snapshots: SnapshotStore,
        knowledge: SqlKnowledge, queue: ReviewQueue, after_change: AfterChange | None = None,
        config: MonitorConfig | None = None, only_unfinished: bool = False) -> dict:
    """One monitoring run for `today`. A day has one run: one that finished is not repeated, one cut off by a restart is
    continued (a fact already taken back is no longer monitored; what was seen once is kept). The run row is locked
    while it runs, so two workers never run the same day. `only_unfinished` is the retry tick: it does nothing unless
    today's run was started and not finished."""
    cfg = config or load_config()
    with engine.begin() as conn:
        if not only_unfinished:
            conn.execute(insert(RUNS).values(tenant_id=tenant_id, run_date=today, started_at=now)
                         .on_conflict_do_nothing(constraint="uq_os_monitor_runs_day"))
    with engine.connect() as lock:  # the lock transaction stays open for the whole run
        row = _lock_run(lock, tenant_id, today)
        if row is None:
            return {"nothing_to_finish": True} if only_unfinished and not _exists(engine, tenant_id, today) \
                else {"locked": True}
        if row.finished_at is not None:
            return {**row.counts, "already_ran": True}
        counts = dict.fromkeys(COUNTS, 0)
        windows = active_windows(engine, tenant_id, today)
        counts["windows"] = len(windows)
        programmes = ProgrammeStore(engine, tenant_id).all() if windows else []
        for w in windows:
            for url, sources in sorted(_facts_by_url(engine, tenant_id, w, programmes, cfg).items()):
                counts["urls"] += 1
                counts["facts"] += len(sources)
                _check_url(url, sources, w, row.id, today, now, gateway, snapshots, knowledge, queue, after_change,
                           cfg, counts, engine, tenant_id)
        lock.execute(update(RUNS).where(RUNS.c.id == row.id).values(finished_at=now, counts=counts))
        lock.commit()
    return counts


def _exists(engine: Engine, tenant_id: str, today: date) -> bool:
    with engine.connect() as conn:
        return conn.execute(select(RUNS.c.id).where(RUNS.c.tenant_id == tenant_id, RUNS.c.run_date == today)).first() is not None


def _sane(text: str, sources: list[_Source], previous, cfg: MonitorConfig) -> str | None:
    """Why this page cannot be trusted to say a quote is gone, or None. Both checks are in config.yaml."""
    if previous is not None and len(previous.text) > 0:
        shrunk = 100 * (len(previous.text) - len(text)) / len(previous.text)
        if shrunk > cfg.sanity_max_shrink_percent:
            return "sanity_shrunk"
    page_norm = normalise(text)
    if len(sources) >= cfg.sanity_no_match_min_facts and not any(quote_on_page(s.fact.quote, page_norm) for s in sources):
        return "sanity_no_quote"
    return None


def _check_url(url, sources, w, run_id, today, now, gateway, snapshots, knowledge, queue, after_change, cfg, counts,
               engine, tenant_id) -> None:
    previous = snapshots.latest(url)  # the last clean page: before the read, so it is what monitoring last trusted
    own = sorted({d for s in sources for d in s.domains})
    page = gateway.fetch_or_record(url, own, [], Scope(region=w.region, family=w.family), refresh=True)
    gone = page.blocked is not None and any(page.blocked == f"http_{c}" for c in cfg.gone_http)
    if page.blocked is not None and not gone:
        counts["guarded" if page.blocked.startswith(_GUARDED) else "unreadable"] += 1  # the guard drops its own
        return
    if not gone and not page.text:
        counts["unreadable"] += 1
        return
    if not gone:
        bad = _sane(page.text, sources, previous, cfg)
        # a page that fails is kept for the record but flagged, so it never becomes "the last clean snapshot"
        snap = snapshots.save(url, page.text, content_type="text/html", fetched_at=page.fetched_at, flagged=bad)
        if bad:
            counts["unreadable"] += 1
            return
        if previous is not None and previous.sha256 != text_hash(page.text):
            counts["page_changed"] += 1
    snapshot_id = None if gone else snap.id
    page_norm = normalise(page.text) if not gone else ""
    for s in sources:
        if gone:
            reason = "page_gone"
        elif not quote_on_page(s.fact.quote, page_norm):
            reason = "quote_gone"
        else:
            _forget(engine, tenant_id, s.fact_id)  # the evidence is back: what was seen once is not a change
            continue
        if _seen_before(engine, tenant_id, s.fact_id, run_id, reason, cfg):
            _take_back(s, reason, url, snapshot_id, run_id, today, knowledge, queue, after_change)
            _forget(engine, tenant_id, s.fact_id)
            counts["taken_back"] += 1
        else:
            counts["seen_once"] += 1


def _forget(engine: Engine, tenant_id: str, fact_id: int) -> None:
    with engine.begin() as conn:
        conn.execute(delete(SEEN).where(SEEN.c.tenant_id == tenant_id, SEEN.c.fact_id == fact_id))


def _seen_before(engine: Engine, tenant_id: str, fact_id: int, run_id: int, reason: str, cfg: MonitorConfig) -> bool:
    """Notes that this run saw the evidence missing; True when enough separate runs have. A change seen only once (a
    page down for a day, a 404 while a site is moved) costs the fact nothing."""
    if cfg.seen_runs_needed <= 1:
        return True
    with engine.begin() as conn:
        first = conn.execute(select(SEEN.c.first_run_id).where(SEEN.c.tenant_id == tenant_id,
                                                               SEEN.c.fact_id == fact_id).with_for_update()).scalar()
        if first is None:
            conn.execute(insert(SEEN).values(tenant_id=tenant_id, fact_id=fact_id, reason=reason, first_run_id=run_id))
            return False
        if first == run_id:
            return False  # the same run again (a resumed one)
        conn.execute(update(SEEN).where(SEEN.c.tenant_id == tenant_id, SEEN.c.fact_id == fact_id).values(reason=reason))
        return True


def _take_back(s: _Source, reason: str, url: str, snapshot_id: int | None, run_id: int, today: date,
               knowledge: SqlKnowledge, queue: ReviewQueue, after_change: AfterChange | None) -> None:
    try:
        knowledge.revise(s.fact_id, status="unconfirmed", recheck="monitor", cause="monitor", cause_ref=str(run_id),
                         actor="monitor", expected_digest=fact_digest(s.fact),
                         conflict_note=f"the official page changed on {today.isoformat()} ({reason})")
    except StaleFact:  # edited while we read the page: the next run looks again
        return
    queue.void_verify(s.fact_id)
    if after_change is not None:
        after_change(s.scope, s.ref, s.field, s.fact_id, "unconfirmed", s.year)
    queue.open_item("change", dedupe_key=f"change:{s.fact_id}", fact_id=s.fact_id, opened_by="monitor",
                    summary=f"The official page changed ({reason}); the fact is not confirmed until it is checked again",
                    payload={"url": url, "reason": reason, "run_id": run_id, "snapshot_id": snapshot_id,
                             "run_date": today.isoformat()})
