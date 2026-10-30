"""Approval completes the plan's documents task (Slice 5 spec S5-D8).

A programme's documents task is done when every artifact it needs is approved: the base SOP, the CV, and the
programme's own SOP when its rules say the programme asks for one. The kernel completes the task (the sole writer),
with the approved texts' SHA-256 as the result, so the pack (Slice 6) knows exactly which text was approved.
"""

from sqlalchemy import Engine, delete, select

from app.os import models
from app.os.artifacts.store import STATEMENT_KINDS, ArtifactStore
from app.os.kernel import IllegalTransition
from app.os.kernel.states import TaskState
from app.os.statements.config import StatementConfig
from app.os.statements.rules import resolve_rules

T = models.tasks


def needed_artifacts(engine: Engine, tenant: str, knowledge, student: str, programme_ref: str | None, year: int,
                     cfg: StatementConfig) -> list[tuple[str, str | None]]:
    out: list[tuple[str, str | None]] = [("sop", None), ("cv", None)]
    if programme_ref is not None and resolve_rules(engine, tenant, knowledge, student, programme_ref, year, cfg,
                                                   "sop").needed:
        out.append(("sop", programme_ref))
    return out


def approved_shas(engine: Engine, tenant: str, student: str) -> dict[tuple[str, str | None], str]:
    store = ArtifactStore(engine, tenant)
    out = {}
    for a in store.list_for(student, STATEMENT_KINDS):
        if a.status == "approved" and (ap := store.approval(a.id)) is not None:
            out[(a.kind, a.programme_ref)] = ap.sha256
    return out


def complete_documents_tasks(engine: Engine, kernel, knowledge, tenant: str, student: str, cfg: StatementConfig,
                             plan_id: int, year: int) -> list[int]:
    """Completes each waiting documents task whose artifacts are all approved. Returns the completed task IDs."""
    if not cfg.documents_task:
        return []
    with engine.connect() as conn:
        tasks = conn.execute(select(T.c.id, T.c.programme_ref).where(
            T.c.tenant_id == tenant, T.c.plan_id == plan_id, T.c.template_key == cfg.documents_task,
            T.c.state == TaskState.WAITING_STUDENT).order_by(T.c.id)).all()
    if not tasks:
        return []
    shas = approved_shas(engine, tenant, student)
    done = []
    for t in tasks:
        need = needed_artifacts(engine, tenant, knowledge, student, t.programme_ref, year, cfg)
        if not all(k in shas for k in need):
            continue
        payload = {"artifacts": {("programme_sop" if p else kind): shas[(kind, p)] for kind, p in need}}
        try:
            if kernel.complete_student_task(t.id, student, payload):
                done.append(t.id)
        except IllegalTransition:
            pass  # it moved on meanwhile: nothing to complete
    return done


def delete_statements(engine: Engine, tenant: str, student: str) -> None:
    """A deleted student's statements go with them: artifacts (with versions and approvals), answers, pasted rules."""
    ArtifactStore(engine, tenant).delete_for(student)
    with engine.begin() as conn:
        for table in (models.statement_answers, models.statement_rules):
            conn.execute(delete(table).where(table.c.tenant_id == tenant, table.c.student_ref == student))
