"""The admin API of the spreadsheet import (P2-T6, R-67, R-68): a template, a dry-run validation, the import itself,
the import log and undo. The file goes in as a multipart upload; the same code as the CLI runs. Admin token."""

import tempfile
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile

from app.os.api.services import Services
from app.os.knowledge.programmes import ProgrammeStore
from app.os.knowledge.sheets.importer import (
    AlreadyImported,
    ImportDeps,
    ImportRefused,
    build_context,
    plan_file,
    run_import,
    wire_other_tasks,
)
from app.os.knowledge.sheets.importlog import ImportLog
from app.os.knowledge.sheets.plan import OWNER_ACCEPTED, REVIEWERS, summarise
from app.os.knowledge.sheets.reader import SheetError
from app.os.knowledge.sheets.template import workbook_bytes
from app.os.knowledge.sheets.undo import UndoRefused, undo_import
from app.os.registry.store import RegistryStore

MAX_BYTES = 20 * 1024 * 1024
# The admin token is the only identity this API carries, so it is the actor on every import and revision. A name typed
# in the form is kept beside it as `note_actor`, never as the actor.
ADMIN_ACTOR = "admin"


def record_out(r) -> dict:
    return {"id": r.id, "file_name": r.file_name, "sha256": r.sha256, "mode": r.mode, "decision_ref": r.decision_ref,
            "batch_ref": r.batch_ref, "actor": r.actor, "note_actor": r.note_actor, "status": r.status, "counts": r.counts,
            "programmes_created": r.programmes_created, "error": r.error, "started_at": r.started_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "undone_at": r.undone_at.isoformat() if r.undone_at else None, "undone_by": r.undone_by}


def row_out(r) -> dict:
    return {"sheet": r.sheet, "row_id": r.row_id, "source_row": r.src_row, "bucket": r.bucket, "level": r.level,
            "reason": r.reason, "detail": r.detail}


def add_import_routes(router: APIRouter, services: Callable[[], Services], require_admin,
                      deps_factory: Callable[[Services], ImportDeps] | None = None) -> None:
    def make_deps(svc: Services, refetch: bool = False) -> ImportDeps:
        if deps_factory is not None:
            return deps_factory(svc)
        deps = ImportDeps(svc.engine, svc.settings.tenant_id, svc.knowledge,
                          RegistryStore(svc.engine, svc.settings.tenant_id),
                          ProgrammeStore(svc.engine, svc.settings.tenant_id))
        if refetch:
            from app.os.knowledge.research.pages import PageGateway

            deps.fetcher = PageGateway(svc.engine, svc.settings.tenant_id, svc.settings)
        return wire_other_tasks(deps)

    async def save(upload: UploadFile, tmp: Path) -> Path:
        data = await upload.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="file too large")
        name = Path(upload.filename or "batch.xlsx").name
        path = tmp / name
        path.write_bytes(data)
        return path

    @router.get("/admin/imports/template", dependencies=[Depends(require_admin)])
    def template() -> Response:
        return Response(workbook_bytes(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": 'attachment; filename="pai-research-batch-template.xlsx"'})

    @router.post("/admin/imports/validate", dependencies=[Depends(require_admin)])
    async def validate(country: str = Form(...), family: str = Form(""), file: UploadFile = File(...),
                       svc: Services = Depends(services)) -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            path = await save(file, Path(tmp))
            try:
                ctx = build_context(make_deps(svc), country=country, mode=OWNER_ACCEPTED, batch_ref=path.stem,
                                    family=family)
                _, results = plan_file(path, ctx)
            except (SheetError, ValueError) as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
        return {"counts": summarise(results), "rows": [row_out(r) for r in results if r.bucket != "accepted"]}

    @router.post("/admin/imports", dependencies=[Depends(require_admin)])
    async def import_file(country: str = Form(...), actor: str | None = Form(None),
                          owner_accepted: str | None = Form(None),
                          reviewers: bool = Form(False), batch_ref: str | None = Form(None), family: str = Form(""),
                          refetch: bool = Form(False), file: UploadFile = File(...),
                          svc: Services = Depends(services)) -> dict:
        if bool(owner_accepted) == reviewers:
            raise HTTPException(status_code=422, detail="give owner_accepted (a decision ref) or reviewers=true")
        with tempfile.TemporaryDirectory() as tmp:
            path = await save(file, Path(tmp))
            try:
                res = run_import(path, make_deps(svc, refetch), mode=OWNER_ACCEPTED if owner_accepted else REVIEWERS,
                                 actor=ADMIN_ACTOR, note_actor=actor, country=country, decision_ref=owner_accepted,
                                 batch_ref=batch_ref, family=family)
            except AlreadyImported as e:
                raise HTTPException(status_code=409, detail=str(e)) from e
            except ImportRefused as e:
                raise HTTPException(status_code=409, detail=str(e)) from e
            except (SheetError, ValueError) as e:
                raise HTTPException(status_code=422, detail=str(e)) from e
        rec = ImportLog(svc.engine, svc.settings.tenant_id).get(res.import_id)
        return {"import_id": res.import_id, "counts": res.counts, "queued_items": res.queued_items,
                "report_csv": rec.report_csv or ""}

    @router.get("/admin/imports/{import_id}/report", dependencies=[Depends(require_admin)])
    def report(import_id: int, svc: Services = Depends(services)) -> Response:
        rec = ImportLog(svc.engine, svc.settings.tenant_id).get(import_id)
        if rec is None or rec.report_csv is None:
            raise HTTPException(status_code=404, detail="no report for this import")
        return Response(rec.report_csv, media_type="text/csv; charset=utf-8", headers={
            "Content-Disposition": f'attachment; filename="import-{import_id}-report.csv"'})

    @router.get("/admin/imports", dependencies=[Depends(require_admin)])
    def listing(svc: Services = Depends(services)) -> dict:
        return {"imports": [record_out(r) for r in ImportLog(svc.engine, svc.settings.tenant_id).list()]}

    @router.get("/admin/imports/{import_id}", dependencies=[Depends(require_admin)])
    def one(import_id: int, svc: Services = Depends(services)) -> dict:
        rec = ImportLog(svc.engine, svc.settings.tenant_id).get(import_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="import not found")
        return record_out(rec)

    @router.post("/admin/imports/{import_id}/undo", dependencies=[Depends(require_admin)])
    def undo(import_id: int, actor: str | None = Form(None), svc: Services = Depends(services)) -> dict:
        try:
            r = undo_import(svc.engine, svc.settings.tenant_id, import_id, actor=ADMIN_ACTOR)
        except KeyError:
            raise HTTPException(status_code=404, detail="import not found") from None
        except UndoRefused as e:
            raise HTTPException(status_code=409, detail={"message": str(e), "conflicts": e.conflicts}) from e
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from e
        return {"facts": r.facts, "registry": r.registry, "programmes": r.programmes, "links": r.links}
