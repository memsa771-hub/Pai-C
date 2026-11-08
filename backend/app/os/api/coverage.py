"""The coverage dashboard API and the intake gate (P2-T9; P2 §4.9; R-34, R-35, R-66). Admin only."""

from collections.abc import Callable
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from app.os import clock
from app.os.api.services import Services
from app.os.coverage import gate, report
from app.os.intakes.store import Intake, IntakeError, IntakeStore


def intake_out(i: Intake) -> dict:
    return {"id": i.id, "region": i.region, "family": i.family, "term": i.term, "year": i.year, "state": i.state,
            "gate_passed_at": i.gate_passed_at.isoformat() if i.gate_passed_at else None}


def report_out(rep: report.Report) -> dict:
    return {
        "intake": intake_out(rep.intake), "green": rep.green,
        "readings": [{"gate": r.gate, "title": r.title, "green": r.green, "checked": r.checked,
                      "items": [asdict(i) for i in r.items]} for r in rep.readings],
        "rows": [asdict(r) for r in rep.rows],
        "suspect_domains": rep.suspect_domains, "open_review_items": rep.open_review_items,
        "workload": asdict(rep.workload),
    }


def add_coverage_routes(router: APIRouter, services: Callable[[], Services], require_admin) -> None:
    @router.get("/admin/intakes", dependencies=[Depends(require_admin)])
    def intakes(svc: Services = Depends(services)) -> dict:
        return {"intakes": [intake_out(i) for i in IntakeStore(svc.engine, svc.settings.tenant_id).list_intakes()]}

    @router.get("/admin/coverage", dependencies=[Depends(require_admin)])
    def coverage(intake: int, svc: Services = Depends(services)) -> dict:
        try:
            return report_out(report.build(svc.engine, svc.settings.tenant_id, intake, clock.now()))
        except IntakeError:
            raise HTTPException(status_code=404, detail="intake not found") from None

    @router.post("/admin/intakes/{intake_id}/current", dependencies=[Depends(require_admin)])
    def make_current(intake_id: int, svc: Services = Depends(services)) -> dict:
        """R-66: refused with the failing items while the intake's gate is red."""
        tenant = svc.settings.tenant_id
        found = IntakeStore(svc.engine, tenant).by_id(intake_id)
        if found is None:
            raise HTTPException(status_code=404, detail="intake not found")
        if found.state != "open":
            raise HTTPException(status_code=409, detail={"message": f"the intake is {found.state}, not open",
                                                          "failing": []})
        try:
            return intake_out(gate.pass_gate(svc.engine, tenant, intake_id, clock.now()))
        except gate.GateRed as e:
            raise HTTPException(status_code=409, detail={"message": str(e), "failing": e.failing}) from None
        except IntakeError as e:  # it changed between the check and the lock
            raise HTTPException(status_code=409, detail={"message": str(e), "failing": []}) from None
