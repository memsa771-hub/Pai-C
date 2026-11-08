"""The daily monitoring job `os.monitor` (P2 spec §4.7, P2-D20, P2-D21; R-27; row 6.24).

For each region and family inside its notice window: group the confirmed and verified facts of the window's intake by
source URL, read each page again, keep the new snapshot, and check each fact's quote on the new page. A quote that is gone,
or a page that is gone, takes the fact back to `unconfirmed` (marker `monitor`): the plans that use it are revised (the steps
it dates wait, `fact_rechecking`) and a `change` item opens in the review queue. A page that cannot be read now (a timeout, a
server error, a block) changes nothing. Facts only change through the Knowledge store; plans only through `after_change`."""

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import Engine, select, update
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
K, RUNS = models.knowledge_facts, models.monitor_runs
# after_change(scope, ref, field, fact_id, status, intake_year): revises the plans that use the fact
AfterChange = Callable[[str, str, str, int, str, int], None]
_GUARDED = ("integrity:", "suspect_domain", "tls_", "insecure_scheme", "redirect_not_official")


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


def run(engine: Engine, tenant_id: str, today: date, now: datetime, *, gateway: PageGateway, snapshots: SnapshotStore,
        knowledge: SqlKnowledge, queue: ReviewQueue, after_change: AfterChange | None = None,
        config: MonitorConfig | None = None) -> dict:
    """One monitoring run for `today`. A day has one run: a run that finished is not repeated, one cut off by a restart is
    continued (a fact already taken back is no longer monitored). Returns the counts."""
    cfg = config or load_config()
    with engine.begin() as conn:
        run_id = conn.execute(insert(RUNS).values(tenant_id=tenant_id, run_date=today, started_at=now)
                              .on_conflict_do_nothing(constraint="uq_os_monitor_runs_day").returning(RUNS.c.id)).scalar()
        if run_id is None:
            done = conn.execute(select(RUNS.c.id, RUNS.c.finished_at, RUNS.c.counts).where(
                RUNS.c.tenant_id == tenant_id, RUNS.c.run_date == today)).one()
            if done.finished_at is not None:
                return {**done.counts, "already_ran": True}
            run_id = done.id
    counts = dict.fromkeys(("windows", "urls", "facts", "taken_back", "unreadable", "guarded", "page_changed"), 0)
    windows = active_windows(engine, tenant_id, today)
    counts["windows"] = len(windows)
    programmes = ProgrammeStore(engine, tenant_id).all() if windows else []
    for w in windows:
        for url, sources in sorted(_facts_by_url(engine, tenant_id, w, programmes, cfg).items()):
            counts["urls"] += 1
            counts["facts"] += len(sources)
            _check_url(url, sources, w, run_id, today, gateway, snapshots, knowledge, queue, after_change, cfg, counts)
    with engine.begin() as conn:
        conn.execute(update(RUNS).where(RUNS.c.id == run_id).values(finished_at=now, counts=counts))
    return counts


def _check_url(url, sources, w, run_id, today, gateway, snapshots, knowledge, queue, after_change, cfg, counts) -> None:
    previous = snapshots.latest(url)  # before the read: the page as monitoring last saw it
    own = sorted({d for s in sources for d in s.domains})
    page = gateway.fetch_or_record(url, own, [], Scope(region=w.region, family=w.family), refresh=True)
    gone = page.blocked is not None and any(page.blocked == f"http_{c}" for c in cfg.gone_http)
    if page.blocked is not None and not gone:
        counts["guarded" if page.blocked.startswith(_GUARDED) else "unreadable"] += 1  # the guard drops its own
        return
    if not gone and not page.text:
        counts["unreadable"] += 1
        return
    snapshot_id = None
    if not gone:
        snap = snapshots.save(url, page.text, content_type="text/html", fetched_at=page.fetched_at)
        snapshot_id = snap.id
        if previous is not None and previous.sha256 != text_hash(page.text):
            counts["page_changed"] += 1
    page_norm = normalise(page.text) if not gone else ""
    for s in sources:
        if gone:
            reason = "page_gone"
        elif not quote_on_page(s.fact.quote, page_norm):
            reason = "quote_gone"
        else:
            continue
        _take_back(s, reason, url, snapshot_id, run_id, today, knowledge, queue, after_change)
        counts["taken_back"] += 1


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
