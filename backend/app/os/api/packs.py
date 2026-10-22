"""The packs API (Slice 6a spec §4), under /v1/os/packs. The student's own packs only: every programme comes from
their plan, and every file is looked up by their student reference. Files are never shown to anyone else."""

import json
import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from app.os.api import self_serve
from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.services import Services
from app.os.artifacts.store import ArtifactStore
from app.os.knowledge.programmes import ProgrammeStore
from app.os.packs.approval import PackIncomplete, PackNotCurrent, approve_pack, complete_review_tasks
from app.os.packs.details import save_details
from app.os.packs.inputs import inputs_sha, load_inputs
from app.os.packs.run import PACK_KIND, enqueue_pack
from app.os.packs.store import PackFileStore, PackItemStore

log = logging.getLogger(__name__)


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DetailsIn(_In):
    fields: dict[str, str | None]


class AddedItem(_In):
    label: str


class ItemsIn(_In):
    tick: list[str] = []
    untick: list[str] = []
    add: list[AddedItem] = []


class ApproveIn(_In):
    sha256: str


class PackOut(BaseModel):
    programme_ref: str
    name: str | None
    university: str | None
    status: str  # building, ready, incomplete, approved, failed
    version: int | None
    approved: bool
    manifest_sha256: str | None
    route_value: str | None
    instructions: list[dict]
    fees: list[dict]
    checklist: list[dict]
    data_sheet: list[dict]
    files: list[dict]


class PacksOut(BaseModel):
    route: str
    programmes: list[PackOut]


def complete_ready_packs(svc: Services, student: str) -> None:
    """Completes a review_pack task that became ready after its pack was approved. Extra work on a read: it never
    turns the read into an error."""
    try:
        plan = self_serve.student_plan(svc.plans, student)
        if plan is not None:
            complete_review_tasks(svc.engine, svc.kernel, svc.settings.tenant_id, student, plan.plan_id)
    except Exception:
        log.exception("pack task completion failed for a student")


def add_pack_routes(router: APIRouter, services: Callable[[], Services]) -> None:
    def plan_of(svc: Services, student: str):
        plan = self_serve.student_plan(svc.plans, student)
        cfg = plan and svc.pack_configs.get(plan.route_key)
        if cfg is None:
            raise HTTPException(status_code=404, detail="no application packs for your route yet: start a plan first")
        return plan, cfg

    def programme_of(svc: Services, student: str, programme_ref: str):
        plan, cfg = plan_of(svc, student)
        if programme_ref not in plan.programmes:
            raise HTTPException(status_code=404, detail="this programme is not in your plan")
        return plan, cfg

    def inputs(svc: Services, plan, cfg, student: str, programme_ref: str):
        book = self_serve.newest_books(svc.plans)[plan.route_key]
        return load_inputs(svc.engine, svc.settings.tenant_id, svc.knowledge, book, cfg,
                           svc.statement_configs.get(plan.route_key), student, programme_ref, plan.year)

    def build(svc: Services, plan, cfg, student: str, programme_ref: str) -> tuple[str, str]:
        """(the workflow ID, the current inputs' SHA-256)."""
        sha = inputs_sha(inputs(svc, plan, cfg, student, programme_ref))
        return enqueue_pack(svc.dbos_client(), svc.settings.tenant_id, student, programme_ref, plan.route_key,
                            plan.year, sha), sha

    def pack_out(svc: Services, student: str, programme_ref: str, art, current_inputs: str) -> dict:
        store = ArtifactStore(svc.engine, svc.settings.tenant_id)
        programme = ProgrammeStore(svc.engine, svc.settings.tenant_id).get(programme_ref)
        out = {"programme_ref": programme_ref, "name": programme.name if programme else None,
               "university": programme.university if programme else None, "status": "building", "version": None,
               "approved": False, "manifest_sha256": None, "route_value": None, "instructions": [], "fees": [],
               "checklist": [], "data_sheet": [], "files": []}
        if art is None or not art.current_version:
            return out
        version = store.version(art.id, art.current_version)
        manifest = json.loads(version.text)
        ap = store.approval(art.id)
        stale = manifest.get("inputs_sha256") != current_inputs  # a rebuild is enqueued: never show it as settled
        out.update(status="building" if stale else art.status, version=version.number, manifest_sha256=version.sha256,
                   approved=ap is not None and ap.version == version.number, route_value=manifest["route_value"],
                   instructions=manifest["instructions"], fees=manifest["fees"], checklist=manifest["checklist"],
                   data_sheet=manifest["data_sheet"],
                   files=[{"key": k, **f} for k, f in sorted(manifest["files"].items())])
        return out

    @router.get("/packs", response_model=PacksOut)
    def packs(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        plan, cfg = plan_of(svc, student)
        complete_ready_packs(svc, student)
        arts = {a.programme_ref: a for a in ArtifactStore(svc.engine, svc.settings.tenant_id).list_for(student)
                if a.kind == PACK_KIND}
        out = []
        for ref in plan.programmes:
            _, current = build(svc, plan, cfg, student, ref)  # the same inputs: the same workflow, built once
            item = pack_out(svc, student, ref, arts.get(ref), current)
            out.append(item)
        return {"route": plan.route_key, "programmes": out}

    @router.post("/packs/{programme_ref}/build", status_code=202)
    def build_pack(programme_ref: str, student: str = Depends(current_student_ref_for_write),
                   svc: Services = Depends(services)) -> dict:
        plan, cfg = programme_of(svc, student, programme_ref)
        return {"workflow_id": build(svc, plan, cfg, student, programme_ref)[0]}

    @router.put("/packs/details")
    def details(body: DetailsIn, student: str = Depends(current_student_ref_for_write),
                svc: Services = Depends(services)) -> dict:
        _, cfg = plan_of(svc, student)
        try:
            save_details(svc.engine, svc.settings.tenant_id, cfg, student, body.fields)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"saved": len(body.fields)}

    @router.put("/packs/{programme_ref}/items")
    def items(programme_ref: str, body: ItemsIn, student: str = Depends(current_student_ref_for_write),
              svc: Services = Depends(services)) -> dict:
        _, cfg = programme_of(svc, student, programme_ref)
        store = PackItemStore(svc.engine, svc.settings.tenant_id)
        known = {i.key for i in cfg.checklist} | {k for k, _ in store.added(student, programme_ref)}
        unknown = sorted(set(body.tick + body.untick) - known)
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown checklist items: {', '.join(unknown)}")
        for key in body.tick:
            store.tick(student, programme_ref, key)
        for key in body.untick:
            store.untick(student, programme_ref, key)
        added = [store.add(student, programme_ref, a.label.strip()) for a in body.add if a.label.strip()]
        return {"added": added}

    @router.get("/packs/{programme_ref}/files/{sha256}")
    def file(programme_ref: str, sha256: str, student: str = Depends(current_student_ref),
             svc: Services = Depends(services)) -> Response:
        programme_of(svc, student, programme_ref)
        f = PackFileStore(svc.engine, svc.settings.tenant_id).get(student, sha256)
        if f is None:
            raise HTTPException(status_code=404, detail="file not found")
        return Response(f.data, media_type=f.content_type,
                        headers={"Content-Disposition": f'attachment; filename="{f.filename}"'})

    @router.post("/packs/{programme_ref}/approve")
    def approve(programme_ref: str, body: ApproveIn, student: str = Depends(current_student_ref_for_write),
                svc: Services = Depends(services)) -> dict:
        plan, _ = programme_of(svc, student, programme_ref)
        try:
            ap = approve_pack(svc.engine, svc.kernel, svc.settings.tenant_id, student, programme_ref, body.sha256,
                              plan.plan_id)
        except (PackNotCurrent, PackIncomplete) as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        return {"sha256": ap.sha256, "version": ap.version}
