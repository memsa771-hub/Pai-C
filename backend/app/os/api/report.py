"""Student reports of a wrong fact (P2-T7, R-28). The routes exist only with OS_REPORTS=1; without it they answer 404."""

from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.os import clock
from app.os.api.deps import current_student_ref, current_student_ref_for_write
from app.os.api.services import Services
from app.os.knowledge.changes import after_fact_change
from app.os.knowledge.review import ReviewQueue
from app.os.monitor.config import load_config, load_texts
from app.os.monitor.reports import ReportError, report_facts
from app.os.my_plan import plan_facts


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str
    text: str | None = Field(None, max_length=2000)


class SourceReportIn(ReportIn):
    url: str = Field(min_length=1, max_length=2000)


def add_report_routes(router: APIRouter, services: Callable[[], Services]) -> None:
    def submit(svc: Services, student: str, fact_ids: list[int], body: ReportIn) -> dict:
        tenant = svc.settings.tenant_id

        def changed(scope, ref, field, fact_id, status, year) -> None:
            after_fact_change(svc.plans, svc.kernel, scope, ref, field, fact_id, status, year, complete=False)

        try:
            return report_facts(svc.engine, tenant, student, fact_ids, body.reason, body.text, clock.now(),
                                knowledge=svc.knowledge, queue=ReviewQueue(svc.engine, tenant, svc.knowledge),
                                after_change=changed)
        except ReportError as e:
            raise HTTPException(status_code=e.status, detail=e.detail) from None

    @router.get("/report/texts")
    def texts(student: str = Depends(current_student_ref)) -> dict:
        t = load_texts()
        return {"reasons": [{"code": r, "label": t[f"reason_{r}"]} for r in load_config().report_reasons],
                "texts": {k: t[k] for k in ("report_link", "report_title", "report_detail_label", "report_submit",
                                            "report_thanks", "report_limit", "report_failed")}}

    @router.get("/report/sources")
    def sources(student: str = Depends(current_student_ref), svc: Services = Depends(services)) -> dict:
        """The source pages of the student's plan that have facts to report: the link shows only under these."""
        return {"urls": sorted({f.url for f in plan_facts(svc, student) if f.url and f.id is not None})}

    @router.post("/facts/{fact_id}/report")
    def report(fact_id: int, body: ReportIn, student: str = Depends(current_student_ref_for_write),
               svc: Services = Depends(services)) -> dict:
        if fact_id not in {f.id for f in plan_facts(svc, student)}:  # only a fact the student's plan shows
            raise HTTPException(status_code=404, detail="fact_not_found")
        return submit(svc, student, [fact_id], body)

    @router.post("/sources/report")
    def report_source(body: SourceReportIn, student: str = Depends(current_student_ref_for_write),
                      svc: Services = Depends(services)) -> dict:
        """The "Report as wrong" link under a source line: every fact of the student's plan with that page, counted
        against the day's allowance as a whole."""
        url = body.url.strip()
        ids = sorted({f.id for f in plan_facts(svc, student) if f.url == url and f.id is not None})
        if not ids:
            raise HTTPException(status_code=404, detail="source_not_found")
        return submit(svc, student, ids, ReportIn(reason=body.reason, text=body.text))
