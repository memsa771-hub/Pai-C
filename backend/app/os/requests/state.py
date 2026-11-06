"""What the compiler knows about the student (P1-T8, D-w6): the evidence level held for each fact and document, and the
facts and documents in question. Levels and codes only, never a value (R-01): the two values of a "which is right" step
are read live from the host when the student looks.

`StudentState` is a plain value the compiler reads; `build` fills it from four sources while the needs gate is on."""

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Literal

import yaml

from app.os.requests import gate
from app.os.requests.keys import LEVELS

LIMITS_FILE = Path(__file__).parent / "limits.yaml"
Origin = Literal["vault", "impossible", "documents"]


@dataclass(frozen=True)
class QuestionRef:
    """Where a question comes from and which record holds it: `vault` (the Vault card ref), `impossible` (the value
    and total keys, `<value>:<total>`), `documents` (the open finding, `finding:<id>`)."""
    origin: Origin
    ref: str


@dataclass(frozen=True)
class StudentState:
    facts: dict[str, str] = field(default_factory=dict)  # fact key -> stated | shown | confirmed (inferred is absent)
    documents: dict[str, str] = field(default_factory=dict)  # document type -> confirmed | uploaded
    questions: dict[str, QuestionRef] = field(default_factory=dict)  # "<fact|document>:<ref>" -> where it comes from

    def level(self, ref: str) -> str | None:
        """The evidence level held for a fact, or None when none is (inferred counts as none)."""
        level = self.facts.get(ref)
        return level if level in LEVELS else None

    def document_met(self, doc_type: str) -> bool:
        """A document meets a need only once the student has confirmed what PAI read (T7's rule)."""
        return self.documents.get(doc_type) == "confirmed"

    def question(self, need_kind: str, ref: str) -> QuestionRef | None:
        return self.questions.get(f"{need_kind}:{ref}")


@cache
def limit_pairs() -> tuple[tuple[str, str], ...]:
    """(value key, total key) pairs from `limits.yaml`."""
    data = yaml.safe_load(LIMITS_FILE.read_text(encoding="utf-8")) or {}
    return tuple((p["value"], p["total"]) for p in data.get("pairs", ()))


def scale_pairs(types) -> list[tuple[str, str]]:
    """The "not above the total" pairs: the document types' `scale_of` fields that name a fact, plus `limits.yaml`."""
    pairs = set(limit_pairs())
    for t in types.values():
        by_name = {f.name: f for f in t.fields}
        for f in t.fields:
            total = by_name.get(f.scale_of) if f.scale_of else None
            if f.fact and total is not None and total.fact:
                pairs.add((f.fact, total.fact))
    return sorted(pairs)


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def build(plans, student_ref: str) -> StudentState | None:
    """None while the needs gate is off. `plans` is the PlanService (its engine and tenant)."""
    from app.os.documents.store import DocumentStore, FindingStore  # late: keep the compiler's import light
    from app.os.eligibility.facts import current_types
    from app.os.ports import fact_questions

    engine, tenant = plans.engine, plans.kernel.tenant_id
    held = gate.on(student_ref, engine=engine, tenant_id=tenant)
    if held is None:
        return None
    facts = {f.key: f.evidence for f in held.facts if f.evidence in LEVELS}
    questions: dict[str, QuestionRef] = {}
    for key, ref in sorted(fact_questions.conflicts(student_ref).items()):
        questions[f"fact:{key}"] = QuestionRef("vault", ref)
    values = {f.key: _number(f.value) for f in held.facts}
    for value_key, total_key in scale_pairs(current_types()):
        value, total = values.get(value_key), values.get(total_key)
        if value is not None and total is not None and value > total:
            questions.setdefault(f"fact:{value_key}", QuestionRef("impossible", f"{value_key}:{total_key}"))
    docs = DocumentStore(engine, tenant).list_for(student_ref)
    documents: dict[str, str] = {}
    for d in docs:
        if documents.get(d.doc_type) != "confirmed":
            documents[d.doc_type] = "confirmed" if d.status == "confirmed" else "uploaded"
    type_of = {d.id: d.doc_type for d in docs}
    for finding in FindingStore(engine, tenant).list_open(student_ref):
        if finding["kind"] != "mismatch":
            continue
        for doc_id, _ in finding["items"]:
            if doc_id in type_of:
                questions.setdefault(f"document:{type_of[doc_id]}", QuestionRef("documents", f"finding:{finding['id']}"))
    return StudentState(facts=facts, documents=documents, questions=questions)
