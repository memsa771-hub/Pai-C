"""The packs API (Slice 6a spec §4), under /v1/os/packs, and the visa file API (Slice 6b spec §4), under
/v1/os/visa. The student's own packs only: every programme comes from their plan, and every file is looked up by
their student reference. Files are never shown to anyone else."""

import json
import logging
from collections.abc import Callable
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from app.os.api import self_serve
from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.services import Services
from app.os.artifacts.store import ArtifactStore
from app.os.knowledge.programmes import ProgrammeStore
from app.os.packs.approval import PackIncomplete, PackNotCurrent, approve_pack, complete_review_tasks
from app.os.packs.details import save_details
from app.os.packs.inputs import inputs_sha, load_inputs
from app.os.packs.funds import required_funds
from app.os.packs.run import PACK_KIND, VISA_KIND, enqueue_pack, latest_attempt
from app.os.packs.store import PackFileStore, PackItemStore
from app.os.packs.visa import VISA_ITEMS, VisaChoiceStore, admitted, preselect

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


class ChoiceIn(_In):
    programme_ref: str | None = None
    reduction: float | None = Field(default=None, ge=0)


class VisaOut(PackOut):
    programme_ref: str | None  # the chosen programme, else the pre-selected one; None: choose one first
    status: str  # no_choice, building, ready, incomplete, approved, failed
    funds: dict | None
    choice: dict  # programme_ref (stored), reduction, preselected, admitted (every admitted programme)
    programmes: list[dict]  # the plan's programmes to choose from


def complete_ready_packs(svc: Services, student: str) -> None:
    """Completes a review_pack task that became ready after its pack was approved. Extra work on a read: it never
    turns the read into an error."""
    try:
        plan = self_serve.student_plan(svc.plans, student)
        if plan is not None:
            for kind in (PACK_KIND, VISA_KIND):  # and a review_visa_file task (Slice 6b)
                complete_review_tasks(svc.engine, svc.kernel, svc.settings.tenant_id, student, plan.plan_id, kind,
                                      lambda ref, kind=kind: current_inputs(svc, plan, student, kind, ref))
    except Exception:
        log.exception("pack task completion failed for a student")


def visa_choice(svc: Services, plan, student: str) -> tuple[str | None, str | None, float, str | None]:
    """(the programme the visa file is for, the stored choice, the reduction, the pre-selected programme). Only one
    admission is pre-selected; with two the student chooses first, and nothing is built until they do."""
    stored = VisaChoiceStore(svc.engine, svc.settings.tenant_id).get(student)
    ref = stored.programme_ref if stored and stored.programme_ref in plan.programmes else None
    pre = preselect(svc.engine, svc.settings.tenant_id, plan.plan_id, plan.programmes)
    return ref or pre, ref, stored.reduction if stored else 0.0, pre


def load_current(svc: Services, plan, student: str, kind: str, programme_ref: str):
    """The inputs a pack (or the visa file) for this programme would be built from now."""
    cfg = (svc.visa_configs if kind == VISA_KIND else svc.pack_configs)[plan.route_key]
    book = self_serve.newest_books(svc.plans)[plan.route_key]
    return load_inputs(svc.engine, svc.settings.tenant_id, svc.knowledge, book, cfg,
                       svc.statement_configs.get(plan.route_key), student, programme_ref, plan.year, kind)


def current_inputs(svc: Services, plan, student: str, kind: str, programme_ref: str | None) -> str | None:
    """The SHA-256 of what would be built now; None when there is nothing to build (no config, no visa choice)."""
    configs = svc.visa_configs if kind == VISA_KIND else svc.pack_configs
    if not configs or plan.route_key not in configs:
        return None
    ref = visa_choice(svc, plan, student)[0] if kind == VISA_KIND else programme_ref
    return None if ref is None else inputs_sha(load_current(svc, plan, student, kind, ref))


def fill_from_manifest(out: dict, store: ArtifactStore, art, current_inputs: str) -> dict:
    """The current manifest's fields into `out` (a PackOut or VisaOut). A manifest built from other inputs than the
    current ones shows as `building` (a rebuild is enqueued): never as settled."""
    if art is None or not art.current_version:
        return out
    version = store.version(art.id, art.current_version)
    manifest = json.loads(version.text)
    ap = store.approval(art.id)
    stale = manifest.get("inputs_sha256") != current_inputs
    settled_status = art.status if art.status in ("ready", "incomplete", "approved", "failed") else "building"
    out.update(status="failed" if art.status == "failed" else "building" if stale else settled_status,
               version=version.number, manifest_sha256=version.sha256,
               approved=ap is not None and ap.version == version.number and not stale,  # final review I1
               route_value=manifest["route_value"],
               instructions=manifest["instructions"], fees=manifest["fees"], checklist=manifest["checklist"],
               data_sheet=manifest["data_sheet"],
               files=[{"key": k, **f} for k, f in sorted(manifest["files"].items())])
    if "funds" in manifest and not stale:
        out["funds"] = manifest["funds"]
    return out


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

    def build(svc: Services, plan, cfg, student: str, programme_ref: str, art,
              retry: bool = False) -> tuple[str, str]:
        """(the workflow ID, the current inputs' SHA-256). The same inputs on the same version are one build; a
        retry after a failure is a new attempt (final review C1)."""
        sha = inputs_sha(inputs(svc, plan, cfg, student, programme_ref))
        version = (art.current_version or 0) if art is not None else 0
        client, tenant = svc.dbos_client(), svc.settings.tenant_id
        attempt = latest_attempt(client, tenant, student, programme_ref, sha, version)
        if retry and art is not None and art.status == "failed":
            attempt += 1
            ArtifactStore(svc.engine, tenant).set_status(art.id, "building")  # the student sees it start at once
        return enqueue_pack(client, tenant, student, programme_ref, plan.route_key, plan.year, sha, version,
                            attempt), sha

    def pack_out(svc: Services, student: str, programme_ref: str, art, current_inputs: str) -> dict:
        store = ArtifactStore(svc.engine, svc.settings.tenant_id)
        programme = ProgrammeStore(svc.engine, svc.settings.tenant_id).get(programme_ref)
        out = {"programme_ref": programme_ref, "name": programme.name if programme else None,
               "university": programme.university if programme else None, "status": "building", "version": None,
               "approved": False, "manifest_sha256": None, "route_value": None, "instructions": [], "fees": [],
               "checklist": [], "data_sheet": [], "files": []}
        if art is not None and art.status == "failed":
            out["status"] = "failed"  # shown as such, with Rebuild; never "being prepared" for ever (final review C1)
        return fill_from_manifest(out, store, art, current_inputs)

    @router.get("/packs", response_model=PacksOut)
    def packs(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        plan, cfg = plan_of(svc, student)
        complete_ready_packs(svc, student)
        arts = {a.programme_ref: a for a in ArtifactStore(svc.engine, svc.settings.tenant_id).list_for(student)
                if a.kind == PACK_KIND}
        out = []
        for ref in plan.programmes:
            _, current = build(svc, plan, cfg, student, ref, arts.get(ref))  # the same inputs: built once
            item = pack_out(svc, student, ref, arts.get(ref), current)
            out.append(item)
        return {"route": plan.route_key, "programmes": out}

    @router.post("/packs/{programme_ref}/build", status_code=202)
    def build_pack(programme_ref: str, student: str = Depends(current_student_ref_for_write),
                   svc: Services = Depends(services)) -> dict:
        plan, cfg = programme_of(svc, student, programme_ref)
        art = next((a for a in ArtifactStore(svc.engine, svc.settings.tenant_id).list_for(student)
                    if a.kind == PACK_KIND and a.programme_ref == programme_ref), None)
        return {"workflow_id": build(svc, plan, cfg, student, programme_ref, art, retry=True)[0]}

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
        plan, cfg = programme_of(svc, student, programme_ref)
        current = inputs_sha(inputs(svc, plan, cfg, student, programme_ref))
        try:
            ap = approve_pack(svc.engine, svc.kernel, svc.settings.tenant_id, student, programme_ref, body.sha256,
                              plan.plan_id, current_inputs=current)
        except (PackNotCurrent, PackIncomplete) as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        return {"sha256": ap.sha256, "version": ap.version}


def add_visa_routes(router: APIRouter, services: Callable[[], Services]) -> None:
    """The visa file (Slice 6b spec §4): one per student, for the programme they choose (S6b-D8)."""

    def visa_of(svc: Services, student: str):
        plan = self_serve.student_plan(svc.plans, student)
        cfg = plan and (svc.visa_configs or {}).get(plan.route_key)
        if cfg is None:
            raise HTTPException(status_code=404, detail="no visa file for your route yet: start a plan first")
        return plan, cfg

    chosen = visa_choice

    def inputs(svc: Services, plan, cfg, student: str, programme_ref: str):
        return load_current(svc, plan, student, VISA_KIND, programme_ref)

    def art_of(svc: Services, student: str):
        return next((a for a in ArtifactStore(svc.engine, svc.settings.tenant_id).list_for(student)
                     if a.kind == VISA_KIND), None)

    def build(svc: Services, plan, cfg, student: str, programme_ref: str, art, retry: bool = False):
        """As the pack's build: the same inputs on the same version are one build; a retry after a failure is a new
        attempt."""
        sha = inputs_sha(inputs(svc, plan, cfg, student, programme_ref))
        version = (art.current_version or 0) if art is not None else 0
        client, tenant = svc.dbos_client(), svc.settings.tenant_id
        attempt = latest_attempt(client, tenant, student, programme_ref, sha, version, VISA_KIND)
        if retry and art is not None and art.status == "failed":
            attempt += 1
            ArtifactStore(svc.engine, tenant).set_status(art.id, "building")
        return enqueue_pack(client, tenant, student, programme_ref, plan.route_key, plan.year, sha, version,
                            attempt, VISA_KIND), sha

    def programmes(svc: Services, plan) -> list[dict]:
        store = ProgrammeStore(svc.engine, svc.settings.tenant_id)
        return [{"programme_ref": ref, "name": p.name if p else None, "university": p.university if p else None}
                for ref in plan.programmes for p in [store.get(ref)]]

    @router.get("/visa", response_model=VisaOut)
    def visa(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        plan, cfg = visa_of(svc, student)
        complete_ready_packs(svc, student)
        ref, stored, reduction, pre = chosen(svc, plan, student)
        listed = programmes(svc, plan)
        named = next((p for p in listed if p["programme_ref"] == ref), {})
        out = {"programme_ref": ref, "name": named.get("name"), "university": named.get("university"),
               "status": "no_choice" if ref is None else "building", "version": None, "approved": False,
               "manifest_sha256": None, "route_value": None, "instructions": [], "fees": [], "checklist": [],
               "data_sheet": [], "files": [], "funds": None, "programmes": listed,
               "choice": {"programme_ref": stored, "reduction": reduction, "preselected": pre,
                          "admitted": [r for r in admitted(svc.engine, svc.settings.tenant_id, plan.plan_id)
                                       if r in plan.programmes]}}
        if ref is None:  # nothing to build yet: the funds still show what the student will need
            if cfg.funds is not None:
                fact = svc.knowledge.route_facts(cfg.route_key, [cfg.funds.fact], plan.year).get(cfg.funds.fact)
                out["funds"] = asdict(required_funds(cfg.funds, fact, reduction))
            return out
        art = art_of(svc, student)
        _, current = build(svc, plan, cfg, student, ref, art)  # the same inputs: built once
        if art is not None and art.status == "failed":
            out["status"] = "failed"
        out = fill_from_manifest(out, ArtifactStore(svc.engine, svc.settings.tenant_id), art, current)
        if out["funds"] is None and cfg.funds is not None:  # still building: the funds from the current inputs
            funds = inputs(svc, plan, cfg, student, ref).funds
            out["funds"] = asdict(funds) if funds is not None else None
        return out

    @router.put("/visa/choice")
    def choice(body: ChoiceIn, student: str = Depends(current_student_ref_for_write),
               svc: Services = Depends(services)) -> dict:
        plan, _ = visa_of(svc, student)
        store = VisaChoiceStore(svc.engine, svc.settings.tenant_id)
        if body.programme_ref is not None and body.programme_ref not in plan.programmes:
            raise HTTPException(status_code=422, detail="this programme is not in your plan")
        if body.programme_ref is not None:
            store.set_programme(student, body.programme_ref)
        if body.reduction is not None:
            try:
                store.set_reduction(student, body.reduction)
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e)) from None
        got = store.get(student)
        return {"programme_ref": got.programme_ref if got else None, "reduction": got.reduction if got else 0.0}

    @router.post("/visa/build", status_code=202)
    def build_visa(student: str = Depends(current_student_ref_for_write), svc: Services = Depends(services)) -> dict:
        plan, cfg = visa_of(svc, student)
        ref = chosen(svc, plan, student)[0]
        if ref is None:
            raise HTTPException(status_code=409, detail="choose the programme for your visa file first")
        return {"workflow_id": build(svc, plan, cfg, student, ref, art_of(svc, student), retry=True)[0]}

    @router.put("/visa/details")
    def details(body: DetailsIn, student: str = Depends(current_student_ref_for_write),
                svc: Services = Depends(services)) -> dict:
        _, cfg = visa_of(svc, student)
        try:
            save_details(svc.engine, svc.settings.tenant_id, cfg, student, body.fields)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from None
        return {"saved": len(body.fields)}

    @router.put("/visa/items")
    def items(body: ItemsIn, student: str = Depends(current_student_ref_for_write),
              svc: Services = Depends(services)) -> dict:
        _, cfg = visa_of(svc, student)
        store = PackItemStore(svc.engine, svc.settings.tenant_id)
        known = {i.key for i in cfg.checklist} | {k for k, _ in store.added(student, VISA_ITEMS)}
        unknown = sorted(set(body.tick + body.untick) - known)
        if unknown:
            raise HTTPException(status_code=422, detail=f"unknown checklist items: {', '.join(unknown)}")
        for key in body.tick:
            store.tick(student, VISA_ITEMS, key)
        for key in body.untick:
            store.untick(student, VISA_ITEMS, key)
        added = [store.add(student, VISA_ITEMS, a.label.strip()) for a in body.add if a.label.strip()]
        return {"added": added}

    @router.get("/visa/files/{sha256}")
    def file(sha256: str, student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> Response:
        visa_of(svc, student)
        f = PackFileStore(svc.engine, svc.settings.tenant_id).get(student, sha256)
        if f is None:
            raise HTTPException(status_code=404, detail="file not found")
        return Response(f.data, media_type=f.content_type,
                        headers={"Content-Disposition": f'attachment; filename="{f.filename}"'})

    @router.post("/visa/approve")
    def approve(body: ApproveIn, student: str = Depends(current_student_ref_for_write),
                svc: Services = Depends(services)) -> dict:
        plan, cfg = visa_of(svc, student)
        ref = chosen(svc, plan, student)[0]
        if ref is None:
            raise HTTPException(status_code=409, detail="choose the programme for your visa file first")
        current = inputs_sha(inputs(svc, plan, cfg, student, ref))
        try:
            ap = approve_pack(svc.engine, svc.kernel, svc.settings.tenant_id, student, ref, body.sha256,
                              plan.plan_id, current_inputs=current, kind=VISA_KIND)
        except (PackNotCurrent, PackIncomplete) as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
        return {"sha256": ap.sha256, "version": ap.version}
