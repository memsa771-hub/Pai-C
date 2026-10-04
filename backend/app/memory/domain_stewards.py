"""Domain interpretation checks between extracted claims and canonical writes.

The extractor interprets free language. A steward resolves which existing
entity that interpretation refers to and checks domain semantics. It returns
decisions/data to the deterministic record reconciler; it does not write rows.
The identity/discriminator contract is the shared RECORD_SPECS registry.
"""

from .errors import MemoryDataError
from .student_schema import RECORD_SPECS


class EntityAmbiguity(MemoryDataError):
    def __init__(self, record_ids: list[str]):
        super().__init__("Several existing records match; confirm which one was meant")
        self.record_ids = record_ids


def _same(left, right):
    if isinstance(left, str) and isinstance(right, str):
        return " ".join(left.casefold().split()) == " ".join(right.casefold().split())
    return left == right


class RecordDomainSteward:
    def __init__(self, kind: str):
        self.kind = kind
        self.contract = RECORD_SPECS[kind]

    def resolve_entity(self, values: dict, existing_rows: list, read_values):
        matches = []
        for row in existing_rows:
            prior = read_values(row)
            if self.kind == "test_attempt" and not any(
                values.get(key) and prior.get(key) == values[key]
                for key in self.contract["discriminators"]
            ):
                if prior == values:
                    matches.append(row)
                continue
            shared = [key for key in self.contract["identity"] if values.get(key) and prior.get(key)]
            if not shared or not all(_same(values[key], prior[key]) for key in shared):
                continue
            if any(values.get(key) is not None and prior.get(key) is not None
                   and not _same(values[key], prior[key])
                   for key in self.contract["discriminators"]):
                continue
            matches.append(row)
        if len(matches) > 1:
            raise EntityAmbiguity([row.id for row in matches])
        return matches[0] if matches else None

    def validate_attribution(self, values, merged, source_type, evidence):
        if self.kind not in {"student_voice_statement", "external_influence"}:
            return
        from .voice_attribution import contained, validated_attribution

        quote = (evidence or {}).get("quote")
        if source_type not in {"conversation", "user_explicit"} or not isinstance(quote, str) or not quote.strip():
            raise MemoryDataError("Student voice and influence require a student quote")
        owner = validated_attribution((evidence or {}).get("attribution"), kind=self.kind,
            quote=quote, message=quote, voice_type=merged.get("voice_type"))
        if owner is None:
            raise MemoryDataError("Student voice and influence require valid claim ownership")
        if self.kind == "student_voice_statement" and "statement" in values and not contained(values["statement"], quote):
            raise MemoryDataError("Student voice statement must be in the student quote")
        if self.kind == "external_influence":
            if values.get("student_alignment") and not contained(owner.get("alignment_quote"), quote):
                raise MemoryDataError("Student alignment requires an exact student quote")
            if values.get("student_response") and not contained(values["student_response"], quote):
                raise MemoryDataError("Student response must be in the student quote")

    def needs_conflict_review(self, *, changed, source_type, current, evidence, os_progress=False):
        if not changed or os_progress or source_type == "user_explicit":
            return False
        return (
            source_type in {"document", "agent", "system"}
            or current.source_type == "document"
            or current.verification_status in {"document_supported", "externally_verified", "verified"}
            or (source_type == "conversation" and (evidence or {}).get("semantic_correction") is not True)
        )
