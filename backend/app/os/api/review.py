"""The review queue API (P2-T5; P2 §4.5, P2-D15, P2-D16). Reviewers use their own token in `X-OS-Reviewer-Token`, not
the shared admin token. The admin token opens items and syncs the queue from confirmed facts."""

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from app.os import models
from app.os.api.services import Services
from app.os.knowledge.changes import after_fact_change
from app.os.knowledge.review import Item, ReviewError, ReviewerStore, ReviewQueue
from app.os.knowledge.review.reviewers import Reviewer
from app.os.knowledge.review.sniff import safe_disposition

REVIEWER_HEADER = "X-OS-Reviewer-Token"
LANG = r"^[a-z]{2,3}$"


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step: str
    outcome: str
    corrected_value: Any = None
    corrected_quote: str | None = Field(None, max_length=4000)
    note: str | None = Field(None, max_length=4000)
    evidence_file_id: int | None = None


class CollectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: Any
    quote: str = Field(max_length=4000)
    url: str = Field(max_length=2000)
    read_method: str = "human"
    language: str | None = Field(None, pattern=LANG)
    note: str | None = Field(None, max_length=4000)
    evidence_file_id: int | None = None


class ResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str
    note: str = Field(max_length=4000)


class OpenItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str
    dedupe_key: str = Field(min_length=1, max_length=300)
    fact_id: int | None = None
    subject: str = ""
    field: str | None = None
    intake_term: str = ""
    intake_year: int | None = None
    owner_ref: str = ""
    summary: str = Field("", max_length=2000)
    payload: dict = Field(default_factory=dict)
    batch_ref: str | None = None


class SyncIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    high_stakes_only: bool | None = None
    batch_ref: str | None = None


def item_out(i: Item) -> dict:
    return {"id": i.id, "kind": i.kind, "status": i.status, "resolution": i.resolution, "fact_id": i.fact_id,
            "subject": i.subject, "field": i.field, "intake_term": i.intake_term, "intake_year": i.intake_year,
            "owner_ref": i.owner_ref, "summary": i.summary, "payload": i.payload, "batch_ref": i.batch_ref,
            "join_count": i.join_count, "opened_by": i.opened_by, "created_at": i.created_at,
            "closed_at": i.closed_at}


def reviewer_out(r: Reviewer) -> dict:
    return {"ref": r.ref, "display_name": r.display_name, "identity": r.identity, "role": r.role, "kind": r.kind,
            "active": r.active}


def queue_for(svc: Services) -> ReviewQueue:
    def changed(scope, ref, field, fact_id, status, year, complete) -> None:
        after_fact_change(svc.plans, svc.kernel, scope, ref, field, fact_id, status, year, complete=complete)

    return ReviewQueue(svc.engine, svc.settings.tenant_id, svc.knowledge, on_fact_change=changed,
                       check_value=svc.plans.check_fact_value)


def _fail(e: ReviewError) -> HTTPException:
    return HTTPException(status_code=e.status, detail=e.detail)


def add_review_routes(router: APIRouter, services: Callable[[], Services], require_admin) -> None:
    def reviewer(x_os_reviewer_token: str | None = Header(None), svc: Services = Depends(services)) -> Reviewer:
        found = ReviewerStore(svc.engine, svc.settings.tenant_id).authenticate(x_os_reviewer_token)
        if found is None:
            raise HTTPException(status_code=401, detail="reviewer token required")
        return found

    @router.get("/review/me")
    def me(who: Reviewer = Depends(reviewer)) -> dict:
        return reviewer_out(who)

    @router.get("/review/items")
    def items(status: str | None = "open", kind: str | None = None, batch_ref: str | None = None,
              who: Reviewer = Depends(reviewer), svc: Services = Depends(services)) -> dict:
        if status not in (None, "", "open", "closed"):
            raise HTTPException(status_code=422, detail="status must be open or closed")
        if kind and kind not in models.REVIEW_ITEM_KINDS:
            raise HTTPException(status_code=422, detail="unknown kind")
        return {"items": [item_out(i) for i in queue_for(svc).list_items(status=status or None, kind=kind,
                                                                         batch_ref=batch_ref)]}

    @router.get("/review/items/{item_id}")
    def item(item_id: int, who: Reviewer = Depends(reviewer), svc: Services = Depends(services)) -> dict:
        try:
            d = queue_for(svc).detail(item_id, who)
        except ReviewError as e:
            raise _fail(e) from None
        return {**d, "item": item_out(d["item"])}

    @router.post("/review/items/{item_id}/review")
    def review(item_id: int, body: ReviewIn, who: Reviewer = Depends(reviewer),
               svc: Services = Depends(services)) -> dict:
        try:
            return queue_for(svc).submit_review(item_id, who, **body.model_dump())
        except ReviewError as e:
            raise _fail(e) from None

    @router.post("/review/items/{item_id}/collect")
    def collect(item_id: int, body: CollectIn, who: Reviewer = Depends(reviewer),
                svc: Services = Depends(services)) -> dict:
        try:
            return queue_for(svc).collect(item_id, who, **body.model_dump())
        except ReviewError as e:
            raise _fail(e) from None

    @router.post("/review/items/{item_id}/resolve")
    def resolve(item_id: int, body: ResolveIn, who: Reviewer = Depends(reviewer),
                svc: Services = Depends(services)) -> dict:
        try:
            return queue_for(svc).resolve(item_id, who, body.outcome, body.note)
        except ReviewError as e:
            raise _fail(e) from None

    @router.post("/review/items/{item_id}/evidence", status_code=201)
    def evidence(item_id: int, request: Request, file: UploadFile = File(...), who: Reviewer = Depends(reviewer),
                 svc: Services = Depends(services)) -> dict:
        q = queue_for(svc)
        declared = request.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > q.policy.evidence_max_bytes + 65536:  # before the body is read
            raise HTTPException(status_code=413, detail="the upload is too large")
        data = file.file.read(q.policy.evidence_max_bytes + 1)  # never read more than the cap allows
        try:
            return q.add_file(item_id, who, file.filename or "evidence", (file.content_type or "").split(";")[0], data)
        except ReviewError as e:
            raise _fail(e) from None

    @router.get("/review/files/{file_id}")
    def get_file(file_id: int, who: Reviewer = Depends(reviewer), svc: Services = Depends(services)) -> Response:
        try:
            meta, data = queue_for(svc).get_file(file_id)
        except ReviewError as e:
            raise _fail(e) from None
        inline = meta["content_type"] == "application/pdf" or meta["content_type"].startswith("image/")
        return Response(content=data, media_type=meta["content_type"], headers={
            "Content-Disposition": safe_disposition("inline" if inline else "attachment", meta["filename"]),
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox", "Cache-Control": "no-store"})

    @router.get("/review/snapshots/{snapshot_id}/original")
    def snapshot_original(snapshot_id: int, who: Reviewer = Depends(reviewer),
                          svc: Services = Depends(services)) -> Response:
        """The PDF or image a snapshot was read from (T3 stores those two kinds only), for the review screen."""
        try:
            data, ctype = queue_for(svc).snapshot_original(snapshot_id)
        except ReviewError as e:
            raise _fail(e) from None
        return Response(content=data, media_type=ctype, headers={
            "Content-Disposition": safe_disposition("inline", f"original-{snapshot_id}"),
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox", "Cache-Control": "no-store"})

    @router.post("/review/batches/{batch_ref}/attest")
    def attest(batch_ref: str, who: Reviewer = Depends(reviewer), svc: Services = Depends(services)) -> dict:
        try:
            return {"batch_ref": batch_ref, "reviewer": who.ref, "new": queue_for(svc).attest(who, batch_ref)}
        except ReviewError as e:
            raise _fail(e) from None

    @router.post("/admin/review/items", status_code=201, dependencies=[Depends(require_admin)])
    def open_item(body: OpenItemIn, svc: Services = Depends(services)) -> dict:
        try:
            item_id, created = queue_for(svc).open_item(**body.model_dump(), opened_by="manual")
        except (ValueError, KeyError) as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"item_id": item_id, "created": created}

    @router.post("/admin/review/sync", dependencies=[Depends(require_admin)])
    def sync(body: SyncIn, svc: Services = Depends(services)) -> dict:
        q = queue_for(svc)
        return {"opened": q.sync(**body.model_dump()), "collect_opened": q.sync_not_readable()}

    @router.get("/admin/review/items/{item_id}/audit", dependencies=[Depends(require_admin)])
    def audit(item_id: int, svc: Services = Depends(services)) -> dict:
        """Every review of an item with the reviewer's identity: for the audit, not for a reviewer's screen."""
        try:
            d = queue_for(svc).audit(item_id)
        except ReviewError as e:
            raise _fail(e) from None
        return {**d, "item": item_out(d["item"])}

    @router.get("/admin/review/export", dependencies=[Depends(require_admin)])
    def export(status: str | None = "open", kind: str | None = None, batch_ref: str | None = None,
               svc: Services = Depends(services)) -> Response:
        """The queue, filtered, as an R-67 spreadsheet; the same file imports back (R-69)."""
        import tempfile
        from pathlib import Path

        from app.os.knowledge.review.export import export_queue

        if kind and kind not in models.REVIEW_ITEM_KINDS:
            raise HTTPException(status_code=422, detail="unknown kind")
        with tempfile.TemporaryDirectory() as tmp:
            path, n, skipped = export_queue(queue_for(svc), Path(tmp) / "review-queue.xlsx", status=status or None,
                                            kind=kind, batch_ref=batch_ref)
            data = path.read_bytes()
        return Response(content=data, headers={
            "Content-Disposition": 'attachment; filename="review-queue.xlsx"', "X-Rows": str(n),
            "X-Items-Without-Row": ",".join(map(str, skipped[:50])) + (f",+{len(skipped) - 50} more" if len(skipped) > 50 else ""),
            "X-Items-Without-Row-Count": str(len(skipped))},
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @router.get("/admin/review/reviewers", dependencies=[Depends(require_admin)])
    def reviewers(svc: Services = Depends(services)) -> dict:
        return {"reviewers": [reviewer_out(r) for r in ReviewerStore(svc.engine, svc.settings.tenant_id).list()]}
