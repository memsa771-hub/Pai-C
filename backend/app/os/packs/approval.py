"""Approving a pack (Slice 6a spec S6a-D7, D8; invariant 5): the student approves the current manifest version, bound
by its SHA-256, and that completes the programme's `review_pack` task through the kernel. A stale or incomplete pack
is refused."""

import json

from sqlalchemy import Engine, select

from app.os import models
from app.os.artifacts.store import Approval, ArtifactStore
from app.os.kernel import IllegalTransition
from app.os.kernel.states import TaskState

REVIEW_TASK = "review_pack"  # the plan task a pack approval completes (each route's playbook has it)
T = models.tasks


class PackNotCurrent(ValueError):
    """There is no pack, or the SHA-256 is not its current version's (an old tab)."""


class PackIncomplete(ValueError):
    """The checklist is not complete."""


def _pack(store: ArtifactStore, student_ref: str, programme_ref: str):
    return next((a for a in store.list_for(student_ref) if a.kind == "pack" and a.programme_ref == programme_ref), None)


def approve_pack(engine: Engine, kernel, tenant_id: str, student_ref: str, programme_ref: str, sha256: str,
                 plan_id: int | None, current_inputs: str | None = None) -> Approval:
    """`current_inputs`: the SHA-256 of the student's material now. A version built from older material is refused
    even if it is still the newest version (an old tab after a change, before the rebuild: final review I1)."""
    store = ArtifactStore(engine, tenant_id)
    art = _pack(store, student_ref, programme_ref)
    if art is None or not art.current_version:
        raise PackNotCurrent("there is no pack for this programme yet")
    version = store.version(art.id, art.current_version)
    stale = current_inputs is not None and json.loads(version.text).get("inputs_sha256") != current_inputs
    if version.sha256 != sha256 or stale:
        raise PackNotCurrent("the pack has changed since you opened it; check it again")
    if not json.loads(version.text)["complete"]:
        raise PackIncomplete("the checklist is not complete")
    approval = store.approve(art.id, version.number)
    if plan_id is not None:
        complete_review_tasks(engine, kernel, tenant_id, student_ref, plan_id)
    return approval


def complete_review_tasks(engine: Engine, kernel, tenant_id: str, student_ref: str, plan_id: int) -> list[int]:
    """Completes each waiting `review_pack` task whose programme's current pack version is approved. Also called when
    the student reads their packs or inbox, so a task that becomes ready after the approval still completes."""
    with engine.connect() as conn:
        tasks = conn.execute(select(T.c.id, T.c.programme_ref).where(
            T.c.tenant_id == tenant_id, T.c.plan_id == plan_id, T.c.template_key == REVIEW_TASK,
            T.c.state == TaskState.WAITING_STUDENT).order_by(T.c.id)).all()
    store, done = ArtifactStore(engine, tenant_id), []
    for t in tasks:
        art = _pack(store, student_ref, t.programme_ref)
        ap = store.approval(art.id) if art is not None else None
        if ap is None or ap.version != art.current_version:
            continue
        try:
            if kernel.complete_student_task(t.id, student_ref, {"artifacts": {"pack": ap.sha256}}):
                done.append(t.id)
        except IllegalTransition:
            pass  # it moved on meanwhile: nothing to complete
    return done
