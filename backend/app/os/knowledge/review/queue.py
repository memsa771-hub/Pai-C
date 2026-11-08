"""The review queue (P2 spec §4.5, P2-D15, P2-D16; R-25, R-42, R-72 collection, R-75).

Items are work for reviewers: `verify` (a confirmed fact waits for its checks), `collect` (a source the OS could not
read, or a check that was unclear), `conflict` (two readings or two reviewers disagree), `report` (R-28), `change`
(monitoring), `suspect_domain` and `import_dispute`. Every action is an `os_fact_reviews` row plus an
`os_fact_revisions` row (through SqlKnowledge); nothing is edited in place.

Trust rules:
- `verified` needs `confirmed` first, then positive checks by different reviewers: a check and an approval for a
  high-stakes fact, one check for any other (policy file). Reviewer kinds that count are policy data: by the owner's
  ruling of 2026-11-07 an AI check 1 and an AI check 2 count as the two checks.
- The checks are independent. Two checks need two distinct reviewer identities (the person, or the model and prompt
  behind an AI reviewer); a reviewer, an admin too, sees no review of an item before giving their own or before it is
  closed (`audit` is the separate admin-only view); the author of a correction or a collection cannot check it.
- A fact read by machine or by hand (`read_method` ocr or human) becomes `confirmed` when a reviewer has compared it
  with the original (R-72). That comparing check does not also count towards `verified`: it needs checks after it.
- A fact whose reading (value, quote, URL, class, read method) changes voids its open verify item at that moment (in
  the store's write), and every write by this queue is refused if the reading is no longer the one decided on.
"""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import IntegrityError

from app.os import clock, models
from app.os.knowledge.fact_classes import fact_class, is_high_stakes
from app.os.knowledge.port import Fact
from app.os.knowledge.research.text import normalise
from app.os.knowledge.research.trust import quote_on_page
from app.os.knowledge.review.policy import ReviewPolicy, load_policy
from app.os.knowledge.review.reviewers import Reviewer
from app.os.knowledge.review.sniff import sniff
from app.os.knowledge.sources.snapshots import SnapshotStore
from app.os.knowledge.store import SqlKnowledge, StaleFact, fact_digest

I = models.review_items
RV = models.fact_reviews
FL = models.review_files
AT = models.review_attestations
F = models.knowledge_facts
RW = models.reviewers
P = models.pages
POSITIVE = ("correct", "approve")
# what a student-facing change hook is told: scope, ref, field, fact id, new status, intake year, complete waiting tasks
FactChanged = Callable[[str, str, str, int, str, int, bool], None]


class ReviewError(Exception):
    """A refused review action; `status` is the HTTP code the API answers with."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _no(detail: str) -> ReviewError:
    return ReviewError(409, detail)


@dataclass(frozen=True)
class Item:
    id: int
    kind: str
    status: str
    resolution: str | None
    fact_id: int | None
    subject: str
    field: str | None
    intake_term: str
    intake_year: int | None
    owner_ref: str
    summary: str
    payload: dict
    batch_ref: str | None
    dedupe_key: str
    join_count: int
    opened_by: str
    created_at: datetime
    closed_at: datetime | None


def _item(row) -> Item:
    return Item(row.id, row.kind, row.status, row.resolution, row.fact_id, row.subject, row.field, row.intake_term,
                row.intake_year, row.owner_ref, row.summary, row.payload or {}, row.batch_ref, row.dedupe_key,
                row.join_count, row.opened_by, row.created_at, row.closed_at)


class ReviewQueue:
    def __init__(self, engine: Engine, tenant_id: str, knowledge: SqlKnowledge, *, policy: ReviewPolicy | None = None,
                 on_fact_change: FactChanged | None = None,
                 check_value: Callable[[str, Any], None] | None = None) -> None:
        """`on_fact_change` revises the plans that use a fact whose trust level moved (the API passes
        `after_fact_change`); `check_value` validates a collected or corrected value the way the admin API does."""
        self.engine = engine
        self.tenant_id = tenant_id
        self.knowledge = knowledge
        self.policy = policy or load_policy()
        self.on_fact_change = on_fact_change
        self.check_value = check_value

    # --- opening items --------------------------------------------------------------------------------------------

    def open_item(self, kind: str, *, dedupe_key: str, fact_id: int | None = None, subject: str = "",
                  field: str | None = None, intake_term: str = "", intake_year: int | None = None, owner_ref: str = "",
                  summary: str = "", payload: dict | None = None, batch_ref: str | None = None,
                  opened_by: str = "manual", conn=None) -> tuple[int, bool]:
        """(item id, created). The same thing opened again while its item is open joins it (`join_count`), so a
        fact reported ten times is one item (P2-D22). With `conn` it is part of the caller's transaction."""
        if kind not in models.REVIEW_ITEM_KINDS:
            raise ValueError(f"unknown review item kind '{kind}'")
        if kind == "verify" and fact_id is None:
            raise ValueError("a verify item needs a fact")
        if fact_id is not None:
            _, _, fname, fact = self.knowledge.get(fact_id)
            field, intake_term, intake_year, owner_ref = fname, fact.intake_term, fact.intake_year, fact.owner_ref
        values = dict(tenant_id=self.tenant_id, kind=kind, fact_id=fact_id, subject=subject, field=field,
                      intake_term=intake_term, intake_year=intake_year, owner_ref=owner_ref, summary=summary,
                      payload=payload or {}, batch_ref=batch_ref, dedupe_key=dedupe_key, opened_by=opened_by)
        with self.knowledge._tx(conn) as c:
            for _ in range(2):
                open_row = c.execute(select(I.c.id).where(I.c.tenant_id == self.tenant_id,
                                                          I.c.dedupe_key == dedupe_key, I.c.status == "open")
                                     .with_for_update()).first()
                if open_row is not None:
                    old = c.execute(select(I.c.payload).where(I.c.id == open_row.id)).scalar() or {}
                    c.execute(update(I).where(I.c.id == open_row.id).values(
                        join_count=I.c.join_count + 1, payload={**(payload or {}), **old}))  # what it had wins
                    if kind == "verify":  # a writer may have skipped this item while it was locked
                        self._void_stale(c, open_row.id)
                    return open_row.id, False
                try:
                    with c.begin_nested():
                        return c.execute(I.insert().values(**values).returning(I.c.id)).scalar_one(), True
                except IntegrityError:
                    continue  # another writer opened it between our read and insert: join theirs
        raise RuntimeError("could not open or join a review item")

    def open_verify(self, fact_id: int, *, opened_by: str = "review", batch_ref: str | None = None,
                    author_ref: str | None = None) -> tuple[int, bool]:
        return self.open_item("verify", dedupe_key=f"verify:{fact_id}", fact_id=fact_id, batch_ref=batch_ref,
                              opened_by=opened_by, payload={"author_ref": author_ref} if author_ref else {})

    def _void_stale(self, conn, item_id: int | None = None) -> int:
        """Closes (as void) open verify items with a review of another reading than the fact has now. A writer skips an
        item a reviewer holds locked (see the store's `_void_reviews`); this catches it afterwards. Returns how many."""
        q = select(I.c.id, I.c.fact_id).where(I.c.tenant_id == self.tenant_id, I.c.kind == "verify",
                                              I.c.status == "open")
        if item_id is not None:
            q = q.where(I.c.id == item_id)
        voided = 0
        for it in conn.execute(q.with_for_update(skip_locked=True)).all():
            fact = self.knowledge.locked(conn, it.fact_id)[3]
            digests = {r.fact_digest for r in conn.execute(select(RV.c.fact_digest).where(RV.c.item_id == it.id))}
            if digests and digests != {fact_digest(fact)}:
                conn.execute(update(I).where(I.c.id == it.id).values(status="closed", resolution="void",
                                                                       closed_at=func.now()))
                voided += 1
        return voided

    def void_verify(self, fact_id: int, conn=None) -> int:
        """Closes the fact's open verify item as void: the fact went back to unconfirmed (monitoring, a report), so
        the checks given so far no longer stand. `sync` opens a new one when the fact is confirmed again."""
        with self.knowledge._tx(conn) as c:
            return c.execute(update(I).where(I.c.tenant_id == self.tenant_id, I.c.fact_id == fact_id,
                                             I.c.kind == "verify", I.c.status == "open")
                             .values(status="closed", resolution="void", closed_at=func.now())).rowcount

    def note_report(self, item_id: int, entry: dict, conn=None) -> None:
        """Adds one student report (reason code, their words, when) to a `report` item. The words stay here: only
        reviewers read them, never another student."""
        with self.knowledge._tx(conn) as conn:
            payload = conn.execute(select(I.c.payload).where(I.c.id == item_id, I.c.tenant_id == self.tenant_id)
                                   .with_for_update()).scalar_one()
            conn.execute(update(I).where(I.c.id == item_id).values(
                payload={**payload, "reports": [*payload.get("reports", []), entry]}))

    def sync(self, *, high_stakes_only: bool | None = None, batch_ref: str | None = None) -> int:
        """Voids stale items, then opens a verify item for every fact that can be checked and has none: confirmed
        facts, and machine or hand readings still waiting for their comparison with the original. Returns how many
        were opened."""
        only_high = self.policy.sync_high_stakes_only if high_stakes_only is None else high_stakes_only
        with self.engine.begin() as conn:
            self._void_stale(conn)
        compare = list(self.policy.compare_with_original)
        with self.engine.connect() as conn:
            rows = conn.execute(select(F.c.id, F.c.field, F.c.fact_class).where(
                F.c.tenant_id == self.tenant_id,
                (F.c.status == "confirmed")
                | ((F.c.status == "unconfirmed") & (F.c.read_method.in_(compare) | F.c.recheck_reason.is_not(None))),
            ).order_by(F.c.id)).all()
        opened = 0
        for r in rows:
            if only_high and not is_high_stakes(fact_class(r.field, r.fact_class)):
                continue
            opened += self.open_verify(r.id, opened_by="manual", batch_ref=batch_ref)[1]
        return opened

    # --- reading --------------------------------------------------------------------------------------------------

    def get_item(self, item_id: int) -> Item:
        with self.engine.connect() as conn:
            row = conn.execute(select(I).where(I.c.id == item_id, I.c.tenant_id == self.tenant_id)).first()
        if row is None:
            raise ReviewError(404, "review item not found")
        return _item(row)

    def list_items(self, *, status: str | None = "open", kind: str | None = None, batch_ref: str | None = None,
                   limit: int = 200) -> list[Item]:
        q = select(I).where(I.c.tenant_id == self.tenant_id)
        if status:
            q = q.where(I.c.status == status)
        if kind:
            q = q.where(I.c.kind == kind)
        if batch_ref:
            q = q.where(I.c.batch_ref == batch_ref)
        with self.engine.connect() as conn:
            return [_item(r) for r in conn.execute(q.order_by(I.c.id).limit(limit)).all()]

    def _reviews(self, item_id: int) -> list:
        with self.engine.connect() as conn:
            return conn.execute(select(RV, RW.c.ref.label("reviewer_ref"), RW.c.kind.label("reviewer_kind"),
                                       RW.c.identity.label("reviewer_identity"), RW.c.display_name).join(RW, RW.c.id == RV.c.reviewer_id)
                                .where(RV.c.item_id == item_id, RV.c.tenant_id == self.tenant_id)
                                .order_by(RV.c.id)).all()

    def _snapshot(self, fact: Fact) -> dict | None:
        """The page the quote was taken from, as the OS stored it (T3's page snapshots). A source read before snapshots
        existed falls back to the page cache (`os_pages`)."""
        if not fact.url:
            return None
        snap = SnapshotStore(self.engine, self.tenant_id).latest(fact.url, clean_only=False)
        if snap is not None:
            return self._snapshot_view(fact, snap.text, snap.fetched_at, snap.read_method, snap.id, snap.flagged)
        with self.engine.connect() as conn:
            row = conn.execute(select(P).where(P.c.tenant_id == self.tenant_id,
                                               (P.c.url == fact.url) | (P.c.final_url == fact.url))
                               .order_by(P.c.fetched_at.desc())).first()
        if row is None or not row.text:
            return None
        return self._snapshot_view(fact, row.text, row.fetched_at, fact.read_method or "fetch", None, None)

    def _snapshot_view(self, fact: Fact, text: str, fetched_at, read_method: str, snapshot_id: int | None,
                       flagged: str | None) -> dict:
        original = SnapshotStore(self.engine, self.tenant_id).original(snapshot_id) if snapshot_id else None
        return {"url": fact.url, "fetched_at": fetched_at, "read_method": read_method, "snapshot_id": snapshot_id,
                "text": text[: self.policy.snapshot_max_chars], "truncated": len(text) > self.policy.snapshot_max_chars,
                "quote_found": quote_on_page(fact.quote, normalise(text)) if fact.quote.strip() else False,
                "flagged": flagged, "original_type": original[1] if original else None}

    def snapshot_original(self, snapshot_id: int) -> tuple[bytes, str]:
        """The original PDF or image a snapshot was read from (T3 keeps those two kinds only)."""
        found = SnapshotStore(self.engine, self.tenant_id).original(snapshot_id)
        if found is None:
            raise ReviewError(404, "no original file for that snapshot")
        return found

    def files_for(self, item_id: int, viewer: Reviewer | None = None, show_all: bool = True) -> list[dict]:
        """The item's evidence files. Who uploaded one is shown under the same rule as the reviews (M3)."""
        with self.engine.connect() as conn:
            rows = conn.execute(select(FL.c.id, FL.c.filename, FL.c.content_type, FL.c.size, FL.c.sha256,
                                       FL.c.created_at, FL.c.uploaded_by, RW.c.ref)
                                .join(RW, RW.c.id == FL.c.uploaded_by)
                                .where(FL.c.item_id == item_id, FL.c.tenant_id == self.tenant_id)
                                .order_by(FL.c.id)).all()
        return [{"id": r.id, "filename": r.filename, "content_type": r.content_type, "size": r.size,
                 "sha256": r.sha256, "uploaded_at": r.created_at,
                 "uploaded_by": r.ref if show_all or (viewer is not None and r.uploaded_by == viewer.id) else None}
                for r in rows]

    def _entries(self, reviews, identity: bool = False) -> list[dict]:
        return [{"id": r.id, "reviewer": r.reviewer_ref, "kind": r.reviewer_kind, "step": r.step,
                 "outcome": r.outcome, "corrected_value": r.corrected_value, "corrected_quote": r.corrected_quote,
                 "note": r.note, "at": r.created_at, **({"identity": r.reviewer_identity} if identity else {})}
                for r in reviews]

    def detail(self, item_id: int, viewer: Reviewer) -> dict:
        """The item with its fact, page and files. Other reviewers' checks (and who uploaded files) are shown to a
        reviewer, an admin too, only after they have given their own or the item is closed: check 2 never sees
        check 1 before it gives its own (§11.2). `audit` is the separate admin-only view."""
        item = self.get_item(item_id)
        reviews = self._reviews(item_id)
        mine = next((r for r in reviews if r.reviewer_id == viewer.id), None)
        visible = item.status == "closed" or mine is not None
        out: dict[str, Any] = {"item": item, "fact": None, "snapshot": None,
                               "files": self.files_for(item_id, viewer, visible)}
        if item.fact_id is not None:
            scope, ref, field, fact = self.knowledge.get(item.fact_id)
            cls = fact_class(field, fact.fact_class)
            out["fact"] = {"id": item.fact_id, "scope": scope, "ref": ref, "field": field, "value": fact.value,
                           "quote": fact.quote, "url": fact.url, "status": fact.status, "checked_at": fact.checked_at,
                           "intake_term": fact.intake_term, "intake_year": fact.intake_year,
                           "owner_ref": fact.owner_ref, "fact_class": cls, "high_stakes": is_high_stakes(cls),
                           "read_method": fact.read_method, "language": fact.language}
            out["snapshot"] = self._snapshot(fact)
        out["reviews"] = self._entries(reviews) if visible else []
        out["my_review"] = None if mine is None else {"step": mine.step, "outcome": mine.outcome}
        return out

    def audit(self, item_id: int) -> dict:
        """Every review of a closed item with the reviewer's identity, for the admin token (not for a reviewer's screen).
        An open item is refused: the admin token must not become a way to read check 1 before check 2 is given."""
        item = self.get_item(item_id)
        if item.status != "closed":
            raise _no("an open item has no audit view: its reviews stay hidden until it is closed")
        return {"item": item, "reviews": self._entries(self._reviews(item_id), identity=True),
                "files": self.files_for(item_id)}

    # --- a check ----------------------------------------------------------------------------------------------------

    def _may_review(self, reviewer: Reviewer, item: Item, step: str) -> None:
        if reviewer.kind not in self.policy.counting_kinds:
            raise ReviewError(403, f"reviews by {reviewer.kind} reviewers do not count (review policy)")
        allowed = {"check": ("checker", "admin"), "approve": ("approver", "admin")}.get(step, ())
        if reviewer.role not in allowed:
            raise ReviewError(403, f"a {reviewer.role} cannot give the '{step}' step")
        if item.payload.get("author_ref") == reviewer.ref:
            raise ReviewError(403, "you wrote this reading; another reviewer must check it")

    def submit_review(self, item_id: int, reviewer: Reviewer, step: str, outcome: str, *, corrected_value: Any = None,
                      corrected_quote: str | None = None, note: str | None = None,
                      evidence_file_id: int | None = None) -> dict:
        """One check of a `verify` item. Returns the item's state after it."""
        pairs = {"check": ("correct", "wrong", "unclear"), "approve": ("approve", "reject")}
        if outcome not in pairs.get(step, ()):
            raise ReviewError(422, f"step '{step}' takes the outcomes {pairs.get(step, ())}")
        if (corrected_value is None) != (corrected_quote is None or not corrected_quote.strip()):
            raise ReviewError(422, "a correction needs both the corrected value and its quote")
        if corrected_value is not None and outcome != "wrong":
            raise ReviewError(422, "only a 'wrong' check carries a correction")
        if outcome in ("wrong", "unclear", "reject") and not (note or "").strip() and corrected_value is None:
            raise ReviewError(422, "say what is wrong or unclear in a note")
        item = self.get_item(item_id)
        if item.kind != "verify":
            raise ReviewError(422, "only a verify item takes checks")
        self._may_review(reviewer, item, step)
        with self.engine.begin() as conn:
            row = conn.execute(select(I).where(I.c.id == item_id, I.c.tenant_id == self.tenant_id)
                               .with_for_update()).one()
            if row.status != "open":
                raise _no("this item is already closed")
            scope, ref, field, fact = self.knowledge.locked(conn, row.fact_id)
            if corrected_value is not None and self.check_value is not None:
                try:
                    self.check_value(field, corrected_value)
                except ValueError as e:
                    raise ReviewError(422, str(e)) from None
            if fact.status != "confirmed" and not self._promotable(fact):
                raise _no(f"the fact is {fact.status}; only a confirmed fact (or a machine or hand reading) is checked")
            if evidence_file_id is not None and not self._file_of(conn, evidence_file_id, item_id):
                raise ReviewError(422, "that evidence file belongs to another item")
            if conn.execute(select(RV.c.id).join(RW, RW.c.id == RV.c.reviewer_id).where(
                    RV.c.item_id == item_id, RW.c.identity == reviewer.identity, RW.c.id != reviewer.id)).first():
                raise _no("a review of this item already came from the same identity; "
                          "two checks need two distinct identities")
            try:
                with conn.begin_nested():
                    conn.execute(RV.insert().values(
                        tenant_id=self.tenant_id, item_id=item_id, fact_id=row.fact_id, reviewer_id=reviewer.id,
                        step=step, outcome=outcome, corrected_value=corrected_value, corrected_quote=corrected_quote,
                        note=note, evidence_file_id=evidence_file_id, fact_digest=fact_digest(fact),
                        high_stakes=is_high_stakes(fact_class(field, fact.fact_class))))
            except IntegrityError:
                raise _no("you have already reviewed this item") from None
        return self.evaluate(item_id, reviewer)

    def _promotable(self, fact: Fact) -> bool:
        """An unconfirmed fact a first positive check can confirm: a machine or hand reading (R-72), or a fact monitoring
        or a student report took back (P2-T7), which a reviewer compares with the page again."""
        return fact.status == "unconfirmed" and (fact.read_method in self.policy.compare_with_original
                                                  or fact.recheck is not None)

    def _file_of(self, conn, file_id: int, item_id: int) -> bool:
        return conn.execute(select(FL.c.id).where(FL.c.id == file_id, FL.c.item_id == item_id,
                                                  FL.c.tenant_id == self.tenant_id)).first() is not None

    def evaluate(self, item_id: int, actor: Reviewer | None = None) -> dict:
        """Applies the checks given so far, all in one transaction (fact changes, follow-up items, closing the item):
        a crash leaves nothing half done, and calling it again is safe. Callbacks that revise plans run after."""
        after: list[Callable[[], None]] = []
        with self.engine.begin() as conn:
            row = conn.execute(select(I).where(I.c.id == item_id, I.c.tenant_id == self.tenant_id)
                               .with_for_update()).one()
            if row.status != "open" or row.kind != "verify":
                return self._state(row)
            resolution = self._decide(conn, row, actor, after)
            if resolution is not None:
                conn.execute(update(I).where(I.c.id == item_id).values(
                    status="closed", resolution=resolution, closed_at=func.now(),
                    closed_by=actor.id if actor else None))
            row = conn.execute(select(I).where(I.c.id == item_id)).one()
        for call in after:
            call()
        return self._state(row)

    def _state(self, row) -> dict:
        status = self.knowledge.get(row.fact_id)[3].status if row.fact_id else None
        return {"item_id": row.id, "item_status": row.status, "resolution": row.resolution, "fact_status": status}

    def _decide(self, conn, item, actor: Reviewer | None, after: list) -> str | None:
        scope, ref, field, fact = self.knowledge.locked(conn, item.fact_id)
        seen = fact_digest(fact)
        cause_ref = str(item.id)
        reviews = conn.execute(select(RV, RW.c.ref.label("rref"), RW.c.kind.label("rkind"),
                                      RW.c.identity.label("rident")).join(RW, RW.c.id == RV.c.reviewer_id)
                               .where(RV.c.item_id == item.id).order_by(RV.c.id)).all()
        if any(r.fact_digest != seen for r in reviews):
            self._reopen_after(item, fact, after)
            return "void"
        if fact.status == "verified":
            return "verified"
        if fact.status != "confirmed" and not self._promotable(fact):
            return "void"  # the fact moved (stale, unconfirmed) while it waited
        guard = dict(cause="review", cause_ref=cause_ref, expected_digest=seen, except_item=item.id, conn=conn)
        try:
            wrong = next((r for r in reviews if r.outcome == "wrong"), None)
            if wrong is not None:
                return self._wrong(conn, item, fact, scope, ref, field, wrong, after, guard)
            if any(r.outcome == "reject" for r in reviews):
                self.open_item("conflict", dedupe_key=f"conflict:verify:{item.id}", fact_id=item.fact_id,
                               summary="A reviewer rejected a reading another reviewer found correct",
                               payload={"source_item": item.id}, opened_by="review", batch_ref=item.batch_ref,
                               conn=conn)
                return "rejected"
            if any(r.outcome == "unclear" for r in reviews):
                self.open_item("collect", dedupe_key=f"collect:{item.fact_id}", fact_id=item.fact_id,
                               summary="A reviewer could not tell if the reading is right; read the original again",
                               payload={"reason": "unclear", "source_item": item.id}, opened_by="review",
                               batch_ref=item.batch_ref, conn=conn)
                return "unclear"
            checks = [r for r in reviews if r.outcome == "correct"]
            promoter = item.payload.get("promoted_by")
            if fact.status == "unconfirmed" and checks:  # compared with the original: now confirmed (R-72)
                self.knowledge.revise(item.fact_id, status="confirmed", actor=checks[0].rref, **guard)
                promoter = checks[0].id
                conn.execute(update(I).where(I.c.id == item.id).values(payload={**item.payload,
                                                                                "promoted_by": promoter}))
                after.append(lambda: self._changed(scope, ref, field, item.fact_id, "confirmed", fact.intake_year, True))
                fact = self.knowledge.locked(conn, item.fact_id)[3]
            # the check that confirmed a machine or hand reading does not also count towards verified (M2)
            counted = [r for r in reviews if r.outcome in POSITIVE and r.id != promoter]
            high = any(r.high_stakes for r in reviews) or is_high_stakes(fact_class(field, fact.fact_class))
            need = self.policy.steps_high_stakes if high else self.policy.steps_other
            has_check = any(r.outcome == "correct" for r in counted)
            has_approval = any(r.outcome == "approve" for r in counted)
            enough = (has_check and has_approval and len({r.rident for r in counted}) >= 2) if need >= 2 \
                else bool(counted)
            persons = sum(1 for r in counted if r.rkind == "person")
            if enough and fact.status == "confirmed" and persons >= self.policy.min_persons:
                self.knowledge.set_status(item.fact_id, "verified", actor=actor.ref if actor else counted[-1].rref,
                                          cause="review", cause_ref=cause_ref, expected_digest=seen, conn=conn)
                return "verified"
            return None
        except StaleFact:  # the reading changed under us after it was read: nothing was written
            self._reopen_after(item, fact, after)
            return "void"

    def _wrong(self, conn, item, fact: Fact, scope: str, ref: str, field: str, wrong, after: list, guard: dict) -> str:
        if wrong.corrected_value is not None:
            self.knowledge.revise(item.fact_id, value=wrong.corrected_value, quote=wrong.corrected_quote,
                                  status="unconfirmed", read_method="human", actor=wrong.rref,
                                  conflict_note=f"corrected by {wrong.rref}; was {fact.value!r}: \"{fact.quote}\"",
                                  **guard)
            resolution = "corrected"
            self.open_verify_later(item, wrong.rref, after)
        else:
            self.knowledge.revise(item.fact_id, status="unconfirmed" if fact.status != "unconfirmed" else fact.status,
                                  conflict_note=f"marked wrong by {wrong.rref}: {wrong.note}", actor=wrong.rref,
                                  **guard)
            resolution = "demoted"
        if fact.status != "unconfirmed":
            after.append(lambda: self._changed(scope, ref, field, item.fact_id, "unconfirmed", fact.intake_year, False))
        return resolution

    def open_verify_later(self, item, author_ref: str, after: list) -> None:
        """The corrected reading needs its own checks, by someone other than the person who corrected it. Opened
        after this item closes (the same fact has one open verify item at a time)."""
        after.append(lambda: self.open_verify(item.fact_id, opened_by="review", batch_ref=item.batch_ref,
                                              author_ref=author_ref))

    def _reopen_after(self, item, fact: Fact, after: list) -> None:
        """The fact changed under review: its reviews no longer apply. A fresh item opens if it can still be checked."""
        if fact.status != "confirmed" and not self._promotable(fact):
            return
        after.append(lambda: self.open_verify(item.fact_id, opened_by="review", batch_ref=item.batch_ref,
                                              author_ref=item.payload.get("author_ref")))

    def _changed(self, scope, ref, field, fact_id, status, year, complete) -> None:
        if self.on_fact_change is not None:
            self.on_fact_change(scope, ref, field, fact_id, status, year, complete)

    # --- collect, resolve -------------------------------------------------------------------------------------------

    def collect(self, item_id: int, reviewer: Reviewer, *, value: Any, quote: str, url: str,
                read_method: str = "human", language: str | None = None, note: str | None = None,
                evidence_file_id: int | None = None) -> dict:
        """A reviewer read the original (R-72): the fact is stored `unconfirmed` with the reading and its evidence,
        and a verify item opens; a different reviewer compares it with the original before it counts."""
        item = self.get_item(item_id)
        if item.kind != "collect":
            raise ReviewError(422, "only a collect item takes a collected reading")
        if reviewer.kind not in self.policy.counting_kinds:
            raise ReviewError(403, f"readings by {reviewer.kind} reviewers do not count (review policy)")
        if not quote.strip():
            raise ReviewError(422, "a reading needs the exact quote")
        parts = urlsplit(url.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ReviewError(422, "the source must be an http or https page address")
        if self.policy.collect_needs_evidence and evidence_file_id is None:
            raise ReviewError(422, "upload the original (a scan, screenshot or PDF) as evidence")
        if read_method not in ("human", "ocr"):
            raise ReviewError(422, "a collected reading is read by 'human' or 'ocr'")
        pl = item.payload
        if self.check_value is not None:
            try:
                self.check_value(item.field, value)
            except ValueError as e:
                raise ReviewError(422, str(e)) from None
        url = url.strip()
        cause_ref = str(item_id)
        new_fact_id = None
        if item.fact_id is None:  # a source that was never read: the fact is created (its own commit; collecting again is safe)
            try:
                scope, ref, field, year = pl["scope"], pl["ref"], item.field, item.intake_year
                if year is None or not field:
                    raise ValueError("the item names no field or intake year")
                fact = Fact(value=value, quote=quote, url=url, checked_at=clock.now(), intake_year=year,
                            status="unconfirmed", intake_term=item.intake_term, owner_ref=item.owner_ref,
                            fact_class=pl.get("fact_class"), read_method=read_method, language=language)
            except (KeyError, ValueError) as e:
                raise ReviewError(422, f"this collect item cannot store a fact: {e}") from None
            new_fact_id = self.knowledge.upsert(scope, ref, field, fact, source="manual", cause="review",
                                                cause_ref=cause_ref, actor=reviewer.ref)
        with self.engine.begin() as conn:
            row = conn.execute(select(I).where(I.c.id == item_id, I.c.tenant_id == self.tenant_id)
                               .with_for_update()).one()
            if row.status != "open":
                raise _no("this item is already closed")
            if evidence_file_id is not None and not self._file_of(conn, evidence_file_id, item_id):
                raise ReviewError(422, "that evidence file belongs to another item")
            if new_fact_id is None:
                fact_id = item.fact_id
                scope, ref, field, _ = self.knowledge.locked(conn, fact_id)
                stored = self.knowledge.revise(fact_id, value=value, quote=quote, url=url, status="unconfirmed",
                                               read_method=read_method, language=language, conflict_note=None,
                                               cause="review", cause_ref=cause_ref, actor=reviewer.ref, conn=conn)
                year = stored.intake_year
            else:
                fact_id = new_fact_id
                stored = self.knowledge.locked(conn, fact_id)[3]
            conn.execute(RV.insert().values(
                tenant_id=self.tenant_id, item_id=item_id, fact_id=fact_id, reviewer_id=reviewer.id, step="collect",
                outcome="collected", corrected_value=value, corrected_quote=quote, note=note,
                evidence_file_id=evidence_file_id, fact_digest=fact_digest(stored),
                high_stakes=is_high_stakes(fact_class(field, stored.fact_class))))
            conn.execute(update(I).where(I.c.id == item_id).values(
                status="closed", resolution="collected", closed_at=func.now(), closed_by=reviewer.id, fact_id=fact_id))
            verify_id, _ = self.open_item("verify", dedupe_key=f"verify:{fact_id}", fact_id=fact_id,
                                          batch_ref=item.batch_ref, opened_by="review",
                                          payload={"author_ref": reviewer.ref}, conn=conn)
        self._changed(scope, ref, field, fact_id, "unconfirmed", year, False)
        return {"item_id": item_id, "item_status": "closed", "resolution": "collected", "fact_id": fact_id,
                "verify_item_id": verify_id}

    def resolve(self, item_id: int, reviewer: Reviewer, outcome: str, note: str) -> dict:
        """Closes an item that is not a verification. `resolved`: it was looked at; `dismissed`: it needs no work.
        On a `report` or `change` item two more outcomes act on the fact (owner ruling 2026-11-08):
        `stands` (and `dismissed` on a report whose fact is being re-checked) puts the fact back to the status it had before it was taken back, clears
        the re-check and revises the plans; `agrees` (a report only) confirms the fact is doubtful for everyone: every
        plan's steps wait, and a `collect` item asks for the original to be read again. The note is kept in the item."""
        if outcome not in ("resolved", "dismissed", "stands", "agrees"):
            raise ReviewError(422, "outcome must be resolved, dismissed, stands or agrees")
        if not note.strip():
            raise ReviewError(422, "say what you checked in a note")
        item = self.get_item(item_id)
        if item.kind == "verify":
            raise ReviewError(422, "a verify item is closed by its checks")
        if outcome in ("stands", "agrees") and item.kind not in ("report", "change"):
            raise ReviewError(422, f"'{outcome}' is for a report or a change")
        if outcome == "agrees" and item.kind != "report":
            raise ReviewError(422, "'agrees' is for a report")
        if item.kind == "report" and outcome == "dismissed" and item.fact_id is not None \
                and self.knowledge.get(item.fact_id)[3].recheck is not None:
            outcome = "stands"  # a dismissed report puts the fact back, if a report took it back; else it just closes
        after: list[Callable[[], None]] = []
        state = None
        with self.engine.begin() as conn:
            row = conn.execute(select(I).where(I.c.id == item_id, I.c.tenant_id == self.tenant_id)
                               .with_for_update()).one()
            if row.status != "open":
                raise _no("this item is already closed")
            if outcome == "stands":
                state = self._restore(conn, row, reviewer, after)
            elif outcome == "agrees":
                state = self._escalate(conn, row, reviewer, after)
            conn.execute(update(I).where(I.c.id == item_id).values(
                status="closed", resolution=outcome, closed_at=func.now(), closed_by=reviewer.id,
                payload={**(row.payload or {}), "resolution_note": note.strip(), "resolved_by": reviewer.ref}))
        for call in after:
            call()
        return {"item_id": item_id, "item_status": "closed", "resolution": outcome, "fact_status": state}

    def _restore(self, conn, item, reviewer: Reviewer, after: list) -> str:
        """The fact stands: back to the status the revision log says it had before monitoring or a report took it back."""
        if item.fact_id is None:
            raise ReviewError(422, "this item has no fact")
        scope, ref, field, fact = self.knowledge.locked(conn, item.fact_id)
        if fact.status != "unconfirmed" or fact.recheck is None:
            raise _no("the fact is not being re-checked any more")
        took = next((r for r in reversed(self.knowledge.revisions(item.fact_id))
                     if r.cause in ("monitor", "report") and r.before and r.after["status"] == "unconfirmed"
                     and r.before["status"] in ("confirmed", "verified", "stale")), None)
        if took is None:
            raise _no("the log shows no earlier status to put back")
        if any(took.after[k] != getattr(fact, k) for k in ("value", "quote", "url")):
            raise _no("the fact changed after it was taken back; check it again instead")
        prev = took.before["status"]
        cause = dict(cause="review", cause_ref=str(item.id), actor=reviewer.ref, conn=conn)
        if prev in ("confirmed", "verified"):
            self.knowledge.set_status(item.fact_id, prev, **cause)  # confirmed or verified clears the re-check
        else:
            self.knowledge.revise(item.fact_id, status=prev, recheck=None, **cause)
        self.void_verify(item.fact_id, conn)
        after.append(lambda: self._changed(scope, ref, field, item.fact_id, prev, fact.intake_year, True))
        return prev

    def _escalate(self, conn, item, reviewer: Reviewer, after: list) -> str:
        """A reviewer agrees with the reports: every plan that uses the fact waits, and the original is read again."""
        scope, ref, field, fact = self.knowledge.locked(conn, item.fact_id)
        if fact.recheck is not None and fact.recheck != "report_escalated":
            self.knowledge.revise(item.fact_id, recheck="report_escalated", cause="review", cause_ref=str(item.id),
                                  actor=reviewer.ref, conn=conn)
            after.append(lambda: self._changed(scope, ref, field, item.fact_id, "unconfirmed", fact.intake_year, False))
        self.open_item("collect", dedupe_key=f"collect:{item.fact_id}", fact_id=item.fact_id, opened_by="review",
                       summary="Reviewers agree this fact looks wrong; read the original again",
                       payload={"reason": "reported", "source_item": item.id}, conn=conn)
        return fact.status

    # --- evidence files -----------------------------------------------------------------------------------------------

    def add_file(self, item_id: int, reviewer: Reviewer, filename: str, content_type: str, data: bytes) -> dict:
        """Stores evidence. What the file is comes from its bytes; a claim that disagrees is refused (C1)."""
        item = self.get_item(item_id)
        if item.status != "open":
            raise _no("this item is already closed")
        if not data:
            raise ReviewError(422, "the file is empty")
        if len(data) > self.policy.evidence_max_bytes:
            raise ReviewError(413, f"the file is larger than {self.policy.evidence_max_bytes} bytes")
        kind = sniff(data)
        if kind is None or kind not in self.policy.evidence_types:
            raise ReviewError(422, f"evidence must be one of {list(self.policy.evidence_types)}")
        claimed = (content_type or "").split(";")[0].strip().lower()
        if claimed not in ("", "application/octet-stream", kind):
            raise ReviewError(422, f"the file is {kind}, not {claimed}")
        name = (filename or "evidence").replace("\\", "/").rsplit("/", 1)[-1][:200] or "evidence"
        with self.engine.begin() as conn:
            fid = conn.execute(FL.insert().values(
                tenant_id=self.tenant_id, item_id=item_id, uploaded_by=reviewer.id, filename=name,
                content_type=kind, size=len(data), sha256=hashlib.sha256(data).hexdigest(), data=data,
            ).returning(FL.c.id)).scalar_one()
        return {"id": fid, "filename": name, "content_type": kind, "size": len(data)}

    def get_file(self, file_id: int) -> tuple[dict, bytes]:
        with self.engine.connect() as conn:
            row = conn.execute(select(FL).where(FL.c.id == file_id, FL.c.tenant_id == self.tenant_id)).first()
        if row is None:
            raise ReviewError(404, "file not found")
        return {"id": row.id, "item_id": row.item_id, "filename": row.filename, "content_type": row.content_type,
                "size": row.size, "sha256": row.sha256}, bytes(row.data)

    # --- batch attestation (P2-D16) ---------------------------------------------------------------------------------------

    def attest(self, reviewer: Reviewer, batch_ref: str) -> bool:
        """"I checked the rows of batch X": one click. True if new. T6's import accepts a reviewer's column only
        for a batch they attested."""
        if not batch_ref.strip():
            raise ReviewError(422, "batch reference is required")
        with self.engine.begin() as conn:
            try:
                with conn.begin_nested():
                    conn.execute(AT.insert().values(tenant_id=self.tenant_id, reviewer_id=reviewer.id,
                                                    batch_ref=batch_ref.strip()))
                return True
            except IntegrityError:
                return False

    def attested(self, reviewer_ref: str, batch_ref: str) -> bool:
        with self.engine.connect() as conn:
            return conn.execute(select(AT.c.id).join(RW, RW.c.id == AT.c.reviewer_id).where(
                AT.c.tenant_id == self.tenant_id, AT.c.batch_ref == batch_ref, RW.c.ref == reviewer_ref,
                RW.c.active.is_(True))).first() is not None
