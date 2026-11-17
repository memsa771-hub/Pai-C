"""Vault events become replan events (P1-T4, R-15). The host tells PAI OS which fact keys of a student changed; for each
open plan of that student whose pinned playbook uses one of them, `student_fact_changed` is recorded once per Vault
version. "Uses" means the playbook's eligibility profile keys (mapped to fact keys through the document types' `fact:`)
plus the constraint and preference keys, which can break a whole plan."""

import logging
from collections.abc import Collection, Mapping

from sqlalchemy import select

from app.os import models
from app.os.documents.types import DocumentType
from app.os.kernel.states import PLAN_OPEN
from app.os.replan import events as ev

log = logging.getLogger("app.os.replan.student_facts")

PLAN_LEVEL_PREFIXES = ("constraint.", "preference.")  # facts about the student's wishes, not about one programme


def need_keys(book) -> set[str]:
    """The fact keys the playbook's steps need (P1-T8, D-w8): their `needs` and the facts their `asks` name. Empty for a
    playbook without needs."""
    documents = {n.document for t in book.tasks for n in t.needs if n.document}
    return {n.fact for t in book.tasks for n in t.needs if n.fact} | {ref for ref in book.asks if ref not in documents}


def used_keys(book, types: Mapping[str, DocumentType]) -> set[str]:
    """The fact keys the playbook's eligibility reads (empty without rules), and those its steps need."""
    keys = need_keys(book)
    if book.eligibility is None:
        return keys
    profile = book.eligibility.profile_fields()
    return keys | {f.fact for t in types.values() for f in t.fields if f.fact and f"{t.key}.{f.name}" in profile}


def changed_used(book, keys: Collection[str], types: Mapping[str, DocumentType]) -> list[str]:
    """The changed keys this playbook uses, sorted."""
    used = used_keys(book, types)
    return sorted(k for k in set(keys) if k in used or k.startswith(PLAN_LEVEL_PREFIXES))


def record_changes(plans, student_ref: str, vault_version: int, keys: Collection[str],
                   types: Mapping[str, DocumentType]) -> int:
    """Records `student_fact_changed` on each open plan of the student that uses a changed key. Deduped by Vault version,
    so a repeated delivery adds nothing. Returns how many events were recorded."""
    P, tenant = models.plans, plans.kernel.tenant_id
    with plans.engine.connect() as conn:
        open_plans = conn.execute(select(P.c.id).where(P.c.tenant_id == tenant, P.c.student_ref == student_ref,
                                                       P.c.status.in_(PLAN_OPEN)).order_by(P.c.id)).scalars().all()
    recorded = 0
    for plan_id in open_plans:
        book = plans._pinned(plan_id)
        used = changed_used(book, keys, types)
        if not used:
            continue
        with plans.engine.begin() as conn:
            recorded += ev.record(conn, tenant, plan_id, "student_fact_changed",
                                  {"keys": used, "vault_version": vault_version}, str(vault_version)) is not None
        if book.declares_needs and set(used) & need_keys(book):  # P1-T8: a request may now be answered
            try:
                plans.recompile(plan_id, "student_fact_changed")
            except Exception as e:  # noqa: BLE001  (logged by type; the hourly recompile is the backup)
                log.error("recompile after a Vault change failed (%s)", type(e).__name__)
    return recorded
