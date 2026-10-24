# -*- coding: utf-8 -*-
"""First-run onboarding — the student's opening statement about themselves.

What this exists for: PAI Counselor starts every new account knowing nothing.
A handful of stable facts asked once, up front, mean the very first reply can
already use their name, where they are, and whether they are studying or
working — instead of spending the first three turns collecting it.

Two design rules this module holds:

1. **It is not a second write path.** Every answer goes through the same
   MemoryCandidate -> MemoryReconciler -> Vault route that conversation
   extraction uses. Onboarding is just a caller with `source_type`
   `user_explicit`, so its facts carry provenance and land in history like
   any other claim. There is no onboarding table and no onboarding copy of a
   student's identity.

2. **It never writes a field PAI needs room to refine.** The status question
   is a coarse category and is stored as `identity.status_category`, NOT as
   `identity.current_status`. Under `latest_wins` a `user_explicit` fact can
   never be superseded by conversation extraction, so putting "Student" into
   `current_status` would permanently block PAI from ever learning
   "Final-year BS Computer Science student". See migration 066.

`user_explicit` also matters for a second reason: `identity.date_of_birth`
carries the `manual_review` conflict policy, and that policy admits exactly
one source — a first-hand statement. Asking the student directly is that
statement, so the answer applies immediately instead of parking as an issue.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.models import User

from .candidates import MemoryCandidateService
from .catalog import vault_catalog
from .errors import MemoryDataError
from .reconciler import MemoryReconciler
from .vault import VaultService


@dataclass(frozen=True)
class OnboardingField:
    """One question, and the canonical Vault key its answer becomes."""
    name: str
    field_key: str
    required: bool = False
    choices: tuple[str, ...] = ()
    max_length: int = 200
    # YYYY, YYYY-MM or YYYY-MM-DD, matching the rest of the student schema.
    is_date: bool = False
    record_field: str | None = None
    allow_other: bool = False
    # Which of the onboarding steps asks it (the UI groups by this).
    step: int = 1
    # A part of another answer (first + last name make fullName); parts are
    # composed, never written on their own.
    part_of: str | None = None
    # Shown pre-selected when nothing is known yet (data, not code).
    default: str | None = None
    # Suggested values for the UI. Unlike `choices`, these do not restrict.
    options: tuple[str, ...] = ()
    # The catalog choice list an answer is read against: "O-Level" or "inter"
    # becomes its code, while `choices` are only the codes offered as chips.
    choice_list: str | None = None


# The order here is the order the form asks them in.
LEGACY_FIELDS: tuple[OnboardingField, ...] = (
    OnboardingField("fullName", "identity.full_name", required=True),
    OnboardingField("preferredName", "identity.preferred_name", required=True),
    OnboardingField(
        "statusCategory", "identity.status_category", required=True,
        choices=("student", "professional", "other"),
    ),
    OnboardingField("nationality", "identity.nationality", required=True),
    OnboardingField(
        "gender", "identity.gender", required=True,
        choices=("male", "female", "other", "undisclosed"),
    ),
    OnboardingField("dateOfBirth", "identity.date_of_birth", required=True, is_date=True),
    OnboardingField("currentCountry", "location.current_country", required=True),
    OnboardingField("currentCity", "location.current_city", required=True),
)

def _catalog_fields() -> tuple[OnboardingField, ...]:
    """The current form, in order: the catalog types marked `onboarding`.

    The catalog is the one place a question lives; its `name` and `parts` are
    the answer keys the frontend sends, its `step` groups the screens.
    """
    asked = sorted((t for t in vault_catalog().types() if t.onboarding), key=lambda t: t.onboarding["order"])
    fields = []
    for spec in asked:
        ask = spec.onboarding
        choices = ask.get("choices")
        choice_list = choices if isinstance(choices, str) else None
        common = dict(
            field_key=spec.key, required=ask.get("required", True), step=ask.get("step", 1),
            is_date=ask["input"] == "date", record_field=ask.get("record_field"),
            allow_other=ask.get("allow_other", False), default=ask.get("default"),
            options=tuple(ask.get("options", ())), choice_list=choice_list,
            choices=tuple(ask.get("shown", ())) if choice_list else tuple(choices or ()))
        parts = ask.get("parts") or ()
        fields += [OnboardingField(part["name"], max_length=part.get("max_length", 200),
                                   part_of=ask["name"], **common) for part in parts]
        if not parts:
            fields.append(OnboardingField(ask["name"], max_length=ask.get("max_length", 200), **common))
    return tuple(fields)


ONBOARDING_FIELDS = _catalog_fields()
# Answers older clients may still send. They are accepted and dropped, so an
# open tab from before a field was retired cannot fail the whole submission.
RETIRED_ANSWERS = frozenset({"replyLanguage"})
FIELDS_BY_NAME = {field.name: field for field in (*LEGACY_FIELDS, *ONBOARDING_FIELDS)}


def _choice_code(field: OnboardingField, text: str) -> Optional[str]:
    """The choice an answer names (an offered chip or any wording of the
    catalog list), or None for the student's own words."""
    if text.casefold() in field.choices:
        return text.casefold()
    return vault_catalog().choice_code(field.choice_list, text) if field.choice_list else None


def _clean(value: Any, field: OnboardingField) -> Optional[str]:
    """Validate one answer into a storable string, or None to skip it.

    Only shape is checked here. The field definition in the Vault is still the
    authority — this is the early, friendlier rejection so the form can say
    which box is wrong instead of surfacing a reconciler error.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise MemoryDataError(f"{field.name} must be text")
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > field.max_length:
        raise MemoryDataError(f"{field.name} is too long")
    code = _choice_code(field, text)
    if (field.choices or field.choice_list) and code is None and not field.allow_other:
        raise MemoryDataError(f"{field.name} must be one of: {', '.join(field.choices)}")
    if code is not None:
        text = code
    if field.is_date:
        import re
        if not re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", text):
            raise MemoryDataError(f"{field.name} must be YYYY, YYYY-MM or YYYY-MM-DD")
        from datetime import date
        try:
            parsed = date.fromisoformat(
                text + ("-01-01" if len(text) == 4 else "-01" if len(text) == 7 else ""))
        except ValueError as exc:
            raise MemoryDataError(f"{field.name} is not a real date") from exc
        if parsed > date.today():
            raise MemoryDataError(f"{field.name} cannot be in the future")
    return text


class OnboardingService:
    """Read the onboarding state, and apply the student's answers."""

    def __init__(self, db):
        self.db = db
        self.vault = VaultService(db)

    # -- state -------------------------------------------------------------

    def owner(self, workspace) -> Optional[User]:
        owner_id = getattr(workspace, "owner_user_id", None)
        if not owner_id:
            return None
        return self.db.execute(select(User).where(User.id == owner_id)).scalar_one_or_none()

    def state(self, workspace) -> dict:
        """Whether the form is still owed, plus anything already known.

        Prefill matters: a student who comes back to a half-finished profile,
        or who was created before this flow existed, should see their own
        values rather than an empty form.
        """
        user = self.owner(workspace)
        facts = self.vault.snapshot(str(workspace.id), include_sensitive=True)
        prefill = {
            field.name: facts[field.field_key]
            for field in FIELDS_BY_NAME.values()
            if isinstance(facts.get(field.field_key), str) and not field.part_of
        }
        # A known full name splits back into its parts (first word, the rest).
        full_name = facts.get("identity.full_name")
        if isinstance(full_name, str) and full_name.strip():
            first, _, rest = full_name.strip().partition(" ")
            parts = [f for f in ONBOARDING_FIELDS if f.part_of == "fullName"]
            if len(parts) == 2:
                prefill.setdefault(parts[0].name, first)
                prefill.setdefault(parts[1].name, rest)
        for field in ONBOARDING_FIELDS:
            if field.default and not prefill.get(field.name):
                prefill[field.name] = field.default
        from .student_records import StudentRecordService
        for field in ONBOARDING_FIELDS:
            if field.record_field:
                rows = StudentRecordService(self.db).list(str(workspace.id), field.field_key)
                if rows:
                    stored = getattr(rows[0], field.record_field, "") or ""
                    # A value saved before the chips were catalog codes ("o-level")
                    # reads as its code, so the chip is selected.
                    prefill[field.name] = (_choice_code(field, stored) or stored) if stored else stored
        # Full name is deliberately collected here, not at signup, and is never
        # guessed from an email address or an OAuth display name.
        return {
            "required": user is not None and user.onboarded_at is None,
            "completedAt": user.onboarded_at.isoformat()
            if user is not None and user.onboarded_at else None,
            "fields": [
                {"name": f.name, "fieldKey": f.field_key, "required": f.required,
                 "choices": list(f.choices), "isDate": f.is_date, "allowOther": f.allow_other,
                 "step": f.step, "default": f.default, "options": list(f.options)}
                for f in ONBOARDING_FIELDS
            ],
            "prefill": {k: v for k, v in prefill.items() if v},
        }

    # -- writes ------------------------------------------------------------

    def apply(self, workspace, answers: dict, *, complete: bool = True) -> dict:
        """Write the answers canonically and stamp the account as onboarded.

        Answers are validated as a set BEFORE anything is written, so a bad
        date never leaves half a profile behind.
        """
        if not isinstance(answers, dict):
            raise MemoryDataError("Onboarding answers must be an object")
        answers = {k: v for k, v in answers.items() if k not in RETIRED_ANSWERS}
        unknown = set(answers) - set(FIELDS_BY_NAME)
        if unknown:
            raise MemoryDataError(f"Unknown onboarding field: {', '.join(sorted(unknown))}")

        cleaned: dict[str, str] = {}
        for name, field in FIELDS_BY_NAME.items():
            value = _clean(answers.get(name), field)
            if value is not None:
                cleaned[name] = value
        # The current contract is the three-step form. Older in-flight clients
        # (the eight-field form, or the four-card form with a full name) still
        # complete with their own required set; their old facts are retained.
        if "firstName" in answers or "lastName" in answers:
            required = ONBOARDING_FIELDS
        elif "level" in answers:
            required = tuple(FIELDS_BY_NAME[name] for name in ("fullName", "level", "currentCity"))
        else:
            required = LEGACY_FIELDS
        missing = [f.name for f in required if f.required and f.name not in cleaned]
        if missing:
            raise MemoryDataError(f"Missing required answer: {', '.join(missing)}")
        # Compose split answers (first + last name) into the field they form,
        # in declared order.
        for target in {f.part_of for f in FIELDS_BY_NAME.values() if f.part_of}:
            parts = [cleaned.pop(f.name) for f in ONBOARDING_FIELDS if f.part_of == target and f.name in cleaned]
            if parts:
                cleaned[target] = " ".join(parts)

        workspace_id = str(workspace.id)
        user = self.owner(workspace)
        saved, rejected = [], {}
        existing_facts = self.vault.snapshot(workspace_id, include_sensitive=True)
        for name, value in cleaned.items():
            field = FIELDS_BY_NAME[name]
            # A returning student's prefilled canonical answer is already
            # satisfied. Do not supersede it with an identical onboarding row
            # or erase its original provenance merely because they continued.
            if existing_facts.get(field.field_key) == value:
                saved.append(field.field_key)
                continue
            candidate = MemoryCandidateService(self.db).propose(
                workspace_id=workspace_id, candidate_type="student_record" if field.record_field else "vault_fact",
                key=field.field_key, proposed_value={field.record_field: value} if field.record_field else value, confidence=1.0,
                source_type="user_explicit", allow_user_explicit=True,
                input_channel="profile",
                subject_user_id=str(user.id) if user else None,
                evidence={"reason": "Stated during onboarding", "capture": "onboarding", "quote": value,
                    **({"catalog_review": {"catalog": field.name, "status": "pending", "student_text": value}}
                       if field.allow_other and _choice_code(field, value) is None else {})},
            )
            result = MemoryReconciler(self.db).reconcile(candidate)
            if result.accepted:
                saved.append(field.field_key)
            else:
                # Never silently swallow it: the student typed this, and a
                # rejection means canonical state did not move.
                rejected[field.field_key] = result.reason or "rejected"

        if user is not None:
            # Completion is a canonical-state guarantee, not merely a form
            # submission stamp. Any reconciliation rejection keeps the gate
            # in place so the UI cannot enter Counselor with missing identity.
            if complete and not rejected:
                # Account/workspace surfaces still read this row. The student
                # is greeted by the first name they gave (no separate
                # "preferred name" is asked or stored); older clients that
                # still send one keep it.
                first = answers.get("firstName")
                first = " ".join(first.split()) if isinstance(first, str) and first.strip() else None
                user.display_name = cleaned.get("preferredName") or first or cleaned["fullName"]
                if user.onboarded_at is None:
                    user.onboarded_at = datetime.now(timezone.utc)
                    from app.runtime.task_runtime import enqueue
                    enqueue(self.db, job_type="counselor.opening", workspace_id=workspace_id,
                            payload={}, idempotency_key=f"counselor:opening:{workspace_id}")

        return {"saved": saved, "rejected": rejected,
                "completed": bool(user and user.onboarded_at)}

