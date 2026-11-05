"""Vault events become replan events (P1-T4, R-15). The host tells PAI OS which fact keys of a student changed; for each
open plan of that student whose pinned playbook uses one of them, `student_fact_changed` is recorded once per Vault
version. "Uses" means the playbook's eligibility profile keys (mapped to fact keys through the document types' `fact:`)
plus the constraint and preference keys, which can break a whole plan."""

from collections.abc import Collection, Mapping

from sqlalchemy import select

from app.os import models
from app.os.documents.types import DocumentType
from app.os.kernel.states import PLAN_OPEN
from app.os.replan import events as ev

PLAN_LEVEL_PREFIXES = ("constraint.", "preference.")  # facts about the student's wishes, not about one programme


def used_keys(book, types: Mapping[str, DocumentType]) -> set[str]:
    """The fact keys the playbook's eligibility reads (empty without rules)."""
    if book.eligibility is None:
        return set()
    profile = book.eligibility.profile_fields()
    return {f.fact for t in types.values() for f in t.fields if f.fact and f"{t.key}.{f.name}" in profile}


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
        used = changed_used(plans._pinned(plan_id), keys, types)
        if not used:
            continue
        with plans.engine.begin() as conn:
            recorded += ev.record(conn, tenant, plan_id, "student_fact_changed",
                                  {"keys": used, "vault_version": vault_version}, str(vault_version)) is not None
    return recorded
