"""Student facts as the profile the playbooks read (P1-T4, P1-D-m). Pure: no database, no clock.

A document-type field may name the StudentFacts key it is read from (`fact:` in the type's YAML). The profile is the
`<doc_type>.<field>` dictionary the evaluator and the playbooks already use, so no playbook changes (running plans pin
their versions). A fact with no value (evidence `unknown`, or no value) gives no profile value, so the evaluator
answers "needs input", never "not eligible"."""

from collections.abc import Mapping
from functools import lru_cache

from app.os.contracts.student_facts import StudentFactsV1
from app.os.documents.types import DocumentType, load_document_types


@lru_cache(maxsize=1)
def default_types() -> Mapping[str, DocumentType]:
    """The shipped document types (the profile code has no mount at hand)."""
    return load_document_types()


def profile_from_facts(facts: StudentFactsV1, types: Mapping[str, DocumentType]) -> dict:
    """`{"<doc_type>.<field>": value}` for every field whose `fact:` key holds a value in `facts`."""
    held = {f.key: f.value for f in facts.facts if f.evidence != "unknown" and f.value is not None}
    return {f"{t.key}.{f.name}": held[f.fact] for t in types.values() for f in t.fields
            if f.fact is not None and f.fact in held}
