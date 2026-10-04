"""Common provenance intake for claims from conversation, voice, profile and files.

This module records what a source asserted. It never writes canonical student
state. Domain routing is based on the existing record schema or field
definition, rather than a second keyword classifier over student language.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import VaultAssertion, VaultAssertionEvidence, VaultEvidence
from .field_definitions import VaultFieldDefinitionService


RECORD_DOMAINS = {
    "education": "education", "course": "education", "test_attempt": "education",
    "work_experience": "experience", "project": "experience", "activity": "experience",
    "exploration_experience": "experience", "research": "experience", "achievement": "experience",
    "skill": "skill", "student_voice_statement": "student_voice",
    "external_influence": "external_influence", "goal": "preference_constraint",
    "financial_sponsor": "preference_constraint", "language_proficiency": "identity",
    "certification": "credential", "credential": "credential", "document": "credential",
    "application": "application", "scholarship_application": "application", "visa": "application",
}


@dataclass(frozen=True)
class VaultInputEnvelope:
    workspace_id: str
    subject_user_id: str | None
    source_type: str
    source_actor: str
    source_event_id: str | None
    source_ref: str | None
    channel: str
    captured_at: datetime
    language: str | None
    trust_metadata: dict[str, Any]


def envelope_for(candidate) -> VaultInputEnvelope:
    evidence = candidate.evidence or {}
    event_id = next(iter(candidate.source_event_ids or []), None)
    file_id = evidence.get("file_id") if candidate.source_type == "document" else None
    channel = candidate.input_channel or (
        "document" if candidate.source_type == "document" else
        "conversation" if candidate.source_type in {"conversation", "user_explicit"} else
        "system"
    )
    authority = evidence.get("authority") if candidate.source_type == "document" else None
    actor = authority if isinstance(authority, str) and authority else (
        "student" if candidate.source_type in {"conversation", "user_explicit"} else candidate.source_type
    )
    return VaultInputEnvelope(
        workspace_id=candidate.workspace_id, subject_user_id=candidate.subject_user_id,
        source_type=candidate.source_type, source_actor=actor,
        source_event_id=str(event_id) if event_id else None,
        source_ref=str(file_id or event_id) if file_id or event_id else None,
        channel=channel, captured_at=candidate.created_at,
        language=None, trust_metadata={"authority": authority} if authority else {},
    )


class VaultDomainRouter:
    def __init__(self, db):
        self.fields = VaultFieldDefinitionService(db)

    def route(self, candidate) -> str:
        if candidate.candidate_type == "student_record":
            return RECORD_DOMAINS.get(candidate.key, "unclassified")
        if candidate.candidate_type == "vault_fact":
            definition = self.fields.get(candidate.key) if candidate.key else None
            return definition.category if definition else "unclassified"
        return "memory"


class VaultAssertionService:
    def __init__(self, db):
        self.db = db
        self.router = VaultDomainRouter(db)

    def record(self, candidate) -> VaultAssertion:
        existing = self.db.execute(select(VaultAssertion).where(
            VaultAssertion.candidate_id == candidate.id,
            VaultAssertion.workspace_id == candidate.workspace_id,
        )).scalar_one_or_none()
        if existing:
            return existing
        envelope = envelope_for(candidate)
        assertion = VaultAssertion(
            workspace_id=envelope.workspace_id, subject_user_id=envelope.subject_user_id,
            candidate_id=candidate.id, domain=self.router.route(candidate),
            predicate=candidate.key or candidate.candidate_type,
            operation=candidate.operation,
            value=candidate.proposed_value if candidate.proposed_value is not None else candidate.content,
            source_type=envelope.source_type, source_actor=envelope.source_actor,
            source_event_id=envelope.source_event_id, source_ref=envelope.source_ref,
            channel=envelope.channel, language=envelope.language,
            trust_metadata=envelope.trust_metadata,
            effective_at=candidate.effective_at,
            captured_at=envelope.captured_at,
        )
        self.db.add(assertion)
        self.db.flush()
        self._link_evidence(assertion, candidate, envelope)
        return assertion

    def _link_evidence(self, assertion, candidate, envelope):
        raw = candidate.evidence or {}
        locator = raw.get("locator") if isinstance(raw.get("locator"), str) else None
        quote = raw.get("quote") if isinstance(raw.get("quote"), str) else None
        source_ref = envelope.source_ref or candidate.id
        identity = json.dumps([envelope.source_type, source_ref, locator, quote],
                              ensure_ascii=False, separators=(",", ":"))
        fingerprint = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        evidence = self.db.execute(select(VaultEvidence).where(
            VaultEvidence.workspace_id == candidate.workspace_id,
            VaultEvidence.fingerprint == fingerprint,
        )).scalar_one_or_none()
        if evidence is None:
            verification = "unverified"
            if envelope.source_type == "document":
                from app.documents.classify import verification_for
                verification = verification_for(envelope.trust_metadata.get("authority") or "unknown")
            try:
                with self.db.begin_nested():
                    evidence = VaultEvidence(
                        workspace_id=candidate.workspace_id, fingerprint=fingerprint,
                        evidence_type=envelope.channel, source_ref=source_ref,
                        authority=envelope.trust_metadata.get("authority"), locator=locator,
                        quote=quote, verification=verification, sensitivity="sensitive",
                    )
                    self.db.add(evidence)
                    self.db.flush()
            except IntegrityError:
                evidence = self.db.execute(select(VaultEvidence).where(
                    VaultEvidence.workspace_id == candidate.workspace_id,
                    VaultEvidence.fingerprint == fingerprint,
                )).scalar_one()
        self.db.add(VaultAssertionEvidence(assertion_id=assertion.id, evidence_id=evidence.id))
        self.db.flush()

    def finish(self, assertion: VaultAssertion, result, candidate) -> None:
        assertion.decision = candidate.status
        assertion.canonical_type = candidate.candidate_type if result.result_id else None
        assertion.canonical_id = result.result_id
        assertion.decision_reason = result.reason
        self.db.flush()

    def refresh_decision(self, candidate) -> None:
        assertion = self.db.execute(select(VaultAssertion).where(
            VaultAssertion.candidate_id == candidate.id,
            VaultAssertion.workspace_id == candidate.workspace_id,
        )).scalar_one_or_none()
        if assertion is not None:
            assertion.decision = candidate.status
            assertion.decision_reason = candidate.rejection_reason
            self.db.flush()
