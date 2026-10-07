"""Read versioned Counselor slots without turning pending claims into Vault facts."""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from sqlalchemy import select

from app.models import CounselorSlotAnswer, EventRecord, ProfileFieldResponse, ProfileRequirement
from app.memory.profile_requirements import ProfileRequirementRegistry, is_filled, value_at
from app.memory.student_snapshot import StudentSnapshot


@dataclass(frozen=True)
class SlotState:
    key: str
    status: str  # answered | pending | valid_unknown | declined | missing
    value: Any = None
    quote: str | None = None

    @property
    def answered(self) -> bool:
        return self.status != "missing"


def short_key(requirement: ProfileRequirement) -> str:
    return requirement.key.removeprefix("discovery.")


def _canonical_value(requirement: ProfileRequirement, snapshot: StudentSnapshot) -> Any:
    if requirement.source_type == "vault_fact":
        return snapshot.fact_value(requirement.source_key)
    if requirement.source_type == "record_presence":
        rows = snapshot.records.get(requirement.source_key, ())
        return rows[0] if rows else None
    if requirement.source_type != "record_field":
        return None
    rows = ProfileRequirementRegistry(None).select_records(requirement, snapshot)
    if short_key(requirement) == "subject_likes":
        rows = [row for row in rows if row.get("voice_type") in {"interest", "dislike"}]
    if short_key(requirement) == "goal_reason":
        rows = [row for row in rows if row.get("voice_type") == "motivation"]
    if short_key(requirement) in {"field_interest", "envisioned_outcome", "timing"}:
        tags = {"field_interest": ("interest", "field_interest"),
                "envisioned_outcome": ("direction", "envisioned_outcome"),
                "timing": ("preference", "target_intake")}
        voice_type, direction = tags[short_key(requirement)]
        rows = [row for row in rows if row.get("voice_type") == voice_type
                and row.get("direction") == direction]
    if short_key(requirement) == "family_wish":
        rows = [row for row in rows if row.get("influencer_type") in {"parent", "sibling", "other"}]
    for row in rows:
        value = value_at(row, requirement.source_path)
        if is_filled(value):
            return value
    # Preserve answers already accepted under the earlier slot-source versions.
    if requirement.source_key == "student_voice_statement":
        key = short_key(requirement)
        if key == "field_interest":
            return snapshot.fact_value("career.primary_interest")
        if key in {"envisioned_outcome", "timing"}:
            path = "details.underlying_objective" if key == "envisioned_outcome" else "details.target_intake"
            for goal in snapshot.records.get("goal", ()):
                value = value_at(goal, path)
                if is_filled(value):
                    return value
    return None


def resolve_slot_states(
    requirements: Sequence[ProfileRequirement], snapshot: StudentSnapshot,
    *, pending: Mapping[str, tuple] | None = None,
    responses: Mapping[str, str] | None = None,
) -> dict[str, SlotState]:
    """Canonical accepted facts win; recent pending answers prevent re-asks."""
    pending = pending or {}
    responses = responses or {}
    states = {}
    for requirement in requirements:
        key = short_key(requirement)
        value = _canonical_value(requirement, snapshot)
        if is_filled(value):
            evidence = ((snapshot.facts.get(requirement.source_key) or {}).get("evidence") or {}
                        if requirement.source_type == "vault_fact" else {})
            quote = evidence.get("quote") if isinstance(evidence, dict) else None
            states[key] = SlotState(key, "answered", value,
                                    quote if isinstance(quote, str) else None)
        elif key in pending:
            answer = pending[key]
            status, value = answer[:2]
            states[key] = SlotState(key, status, value,
                                    answer[2] if len(answer) > 2 else None)
        elif responses.get(requirement.key) in {"valid_unknown", "declined"}:
            states[key] = SlotState(key, responses[requirement.key])
        else:
            states[key] = SlotState(key, "missing")
    return states


def applicable(requirement: ProfileRequirement, states: Mapping[str, SlotState],
               snapshot: StudentSnapshot) -> bool:
    conditions = requirement.applicability or {}
    if not isinstance(conditions, dict):
        raise ValueError(f"Invalid slot applicability: {requirement.key}")
    for condition, expected in conditions.items():
        if condition == "slot_value":
            state = states.get(str(expected))
            if state is None or not is_filled(state.value):
                return False
        elif condition == "slot_missing":
            state = states.get(str(expected))
            if state is not None and is_filled(state.value):
                return False
        elif condition == "family_mentioned":
            known = any(row.get("influencer_type") in {"parent", "sibling", "other"}
                        for row in snapshot.records.get("external_influence", ())) or is_filled(
                states.get("family_wish", SlotState("family_wish", "missing")).value)
            if known != expected:
                return False
        elif condition == "working_now":
            known = (bool(snapshot.records.get("work_experience"))
                     or snapshot.fact_value("identity.status_category") == "professional")
            if known != expected:
                return False
        else:
            raise ValueError(f"Unsupported slot condition: {condition}")
    return True


def next_open_slot(requirements: Sequence[ProfileRequirement],
                   states: Mapping[str, SlotState], snapshot: StudentSnapshot,
                   stage: str) -> ProfileRequirement | None:
    """Select by registry priority after applying conditions and answered state."""
    ordered = sorted((r for r in requirements if r.stage == stage),
                     key=lambda r: (-r.priority, r.key))
    return next((r for r in ordered if applicable(r, states, snapshot)
                 and not states.get(short_key(r), SlotState(short_key(r), "missing")).answered), None)


class CounselorSlotRegistry:
    def __init__(self, db):
        self.db = db
        self.requirements = ProfileRequirementRegistry(db)

    def active(self) -> list[ProfileRequirement]:
        return [row for row in self.requirements.active()
                if row.stage in {"foundation", "direction", "summary"}]

    def pending_recent(self, workspace_id: str, *, before_timestamp: int | None = None) -> dict[str, tuple]:
        """Only answers from the last five actual student messages count."""
        query = select(EventRecord.id).where(
            EventRecord.network_id == workspace_id,
            EventRecord.type == "workspace.message.posted",
            EventRecord.source.like("human:%"),
        )
        if before_timestamp is not None:
            query = query.where(EventRecord.timestamp <= before_timestamp)
        event_ids = self.db.execute(query.order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())
                                    .limit(5)).scalars().all()
        if not event_ids:
            return {}
        rows = self.db.execute(select(CounselorSlotAnswer).join(
            EventRecord, EventRecord.id == CounselorSlotAnswer.source_event_id,
        ).where(
            CounselorSlotAnswer.workspace_id == workspace_id,
            CounselorSlotAnswer.source_event_id.in_(event_ids),
        ).order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())).scalars().all()
        answers: dict[str, tuple] = {}
        for row in rows:
            answers.setdefault(row.slot_key, (row.status, row.value, row.quote))
        return answers

    def states(self, workspace_id: str, snapshot: StudentSnapshot,
               *, before_timestamp: int | None = None) -> dict[str, SlotState]:
        responses = {row.requirement_key: row.status for row in self.db.execute(
            select(ProfileFieldResponse).where(ProfileFieldResponse.workspace_id == workspace_id)
        ).scalars()}
        return resolve_slot_states(self.active(), snapshot,
                                   pending=self.pending_recent(workspace_id, before_timestamp=before_timestamp),
                                   responses=responses)
