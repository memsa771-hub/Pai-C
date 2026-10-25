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

Current education is asked exactly (EDUCATION_FOCUS_SPEC section 1): the level,
then the follow-ups that level has (group, subjects, technology or field), then
status and year. The catalog declares them as `follow_ups` with `depends_on`,
and all answers for one record type are written as ONE record, so the Vault
never holds a level without the group asked beside it.
"""

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select

from app.models import User

from .candidates import MemoryCandidateService
from .catalog import norm, vault_catalog
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
    # Follow-ups: shown only while `depends_on` holds ({field, values, and}).
    depends_on: dict | None = None
    multi: bool = False
    # A choice list that is not in the catalog (the study fields), handed in
    # by the caller because app.memory does not read PAI C's policy data.
    source: str | None = None
    searchable: bool = False
    # An Intermediate group decides the stored qualification (Pre-Medical -> fsc).
    level_by_choice: dict | None = None
    is_year: bool = False
    # Copy key when several questions share a name (the year is asked three ways).
    label_key: str | None = None
    # The chips' own wording (Bachelor's), over the catalog label (Bachelor).
    chip_labels: dict | None = None


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
            allow_other=ask.get("allow_other", False), default=ask.get("default"), chip_labels=ask.get("labels"),
            options=tuple(ask.get("options", ())), choice_list=choice_list,
            choices=tuple(ask.get("shown", ())) if choice_list else tuple(choices or ()))
        parts = ask.get("parts") or ()
        fields += [OnboardingField(part["name"], max_length=part.get("max_length", 200),
                                   part_of=ask["name"], **common) for part in parts]
        if not parts:
            fields.append(OnboardingField(ask["name"], max_length=ask.get("max_length", 200), **common))
        for follow in ask.get("follow_ups", ()):
            listed = follow.get("choices")
            listed_name = listed if isinstance(listed, str) else None
            offered = (follow.get("shown") or [c.code for c in vault_catalog().choices(listed_name)]
                       if listed_name else listed or ())
            fields.append(OnboardingField(
                follow["name"], field_key=spec.key, step=common["step"], required=follow.get("required", True),
                record_field=follow["record_field"], choice_list=listed_name, choices=tuple(offered),
                depends_on=follow["depends_on"], multi=follow.get("multi", False), source=follow.get("source"),
                searchable=follow.get("searchable", False), level_by_choice=follow.get("level_by_choice"),
                is_year=follow["input"] == "year", label_key=follow.get("label")))
    return tuple(fields)


ONBOARDING_FIELDS = _catalog_fields()
# Answers older clients may still send. They are accepted and dropped, so an
# open tab from before a field was retired cannot fail the whole submission.
RETIRED_ANSWERS = frozenset({"replyLanguage"})
# The questions always asked. Follow-ups may share a name (the Matric group and
# the Intermediate group), so they are resolved against the answers instead.
FIELDS_BY_NAME = {field.name: field for field in (*LEGACY_FIELDS, *ONBOARDING_FIELDS) if not field.depends_on}
FOLLOW_UPS = tuple(field for field in ONBOARDING_FIELDS if field.depends_on)
KNOWN_ANSWERS = frozenset(field.name for field in (*LEGACY_FIELDS, *ONBOARDING_FIELDS))
# A level only a group decides (fsc, ics, icom, fa) -> the chip that asks it.
_PARENT_CHIP = {code: field.depends_on["values"][0] for field in FOLLOW_UPS if field.level_by_choice
                for code in field.level_by_choice.values()}


def _chip_label(field: OnboardingField, code: str) -> str:
    return (field.chip_labels or {}).get(code) or vault_catalog().label(field.choice_list, code)


def _redirect(field: OnboardingField, value: Any) -> Optional[str]:
    """The chip an Other answer really names ("FSc" -> intermediate), or None.

    Other is for an education the chips do not cover. Typed text that is a
    level we offer would skip that chip's group, subjects or field, and a
    level only a group decides (fsc) is never taken as the level itself.
    """
    if not (field.allow_other and field.choice_list and field.choices and isinstance(value, str)):
        return None
    text = " ".join(value.split())
    if text in field.choices:
        return None
    code = vault_catalog().choice_code(field.choice_list, text)
    if code is None or code == "other":
        return None
    chip = _PARENT_CHIP.get(code, code)
    return chip if chip in field.choices else None


def _redirects(field: OnboardingField) -> dict:
    """Every normalised wording of a level -> its chip, so the form can say
    "Choose Intermediate above" on step 2 instead of failing at the end."""
    if not (field.allow_other and field.choice_list and field.choices):
        return {}
    out = {}
    for choice in vault_catalog().choices(field.choice_list):
        chip = _PARENT_CHIP.get(choice.code, choice.code)
        if choice.code == "other" or chip not in field.choices:
            continue
        for wording in (choice.code, choice.label, *choice.synonyms, choice.code.replace("_", " ")):
            out[norm(wording)] = chip
    return out
_NUMBERED = re.compile(r"_(\d+)$")


def _visible(condition: Optional[dict], answers: dict) -> bool:
    """Whether a follow-up is shown for these answers.

    Only answers that were themselves shown are in `answers`, so the chain
    holds without walking it: year needs a status, status needs a level.
    """
    if not condition:
        return True
    answer = answers.get(condition["field"])
    shown = bool(answer) if condition.get("values") is None else answer in condition["values"]
    return shown and _visible(condition.get("and"), answers)


def _record_schema(field: OnboardingField) -> dict:
    """The record spec's schema at a field's dotted path (details.current_year)."""
    from .student_schema import RECORD_SPECS
    schema = {"properties": RECORD_SPECS[field.field_key]["properties"]}
    for part in field.record_field.split("."):
        schema = schema.get("properties", {}).get(part, {})
    return schema


def _read(row, path: str):
    """A record row's value at a dotted path (details live in a JSON column)."""
    node = row
    for part in path.split("."):
        node = node.get(part) if isinstance(node, dict) else getattr(node, part, None)
    return node


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

    def __init__(self, db, sources: Optional[dict] = None):
        self.db = db
        self.vault = VaultService(db)
        # Choice lists that live outside the catalog: name -> [(code, label)].
        self.sources = sources or {}

    # -- follow-ups --------------------------------------------------------

    def _offered(self, field: OnboardingField) -> list[tuple[str, str]]:
        """(code, label) for each chip a follow-up shows."""
        if field.source:
            return [(code, label) for code, label in self.sources.get(field.source, ())]
        if field.choice_list:
            return [(code, _chip_label(field, code)) for code in field.choices]
        return [(code, code) for code in field.choices]

    def _code(self, field: OnboardingField, text: str) -> Optional[str]:
        """The code an answer names for this follow-up, or None."""
        if field.source:
            return next((code for code, label in self._offered(field)
                         if text.casefold() in (code.casefold(), label.casefold())), None)
        return _choice_code(field, text)

    def _clean_follow_up(self, value: Any, field: OnboardingField):
        """A follow-up answer as its code(s) or year, or None when unanswered."""
        if value is None or value == "" or value == []:
            return None
        if field.multi:
            if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
                raise MemoryDataError(f"{field.name} must be a list")
            codes = [self._code(field, " ".join(v.split())) for v in value if v.strip()]
            if None in codes:
                raise MemoryDataError(f"{field.name} must be from: {', '.join(field.choices)}")
            return list(dict.fromkeys(codes))[:30] or None
        if not isinstance(value, str):
            raise MemoryDataError(f"{field.name} must be text")
        text = " ".join(value.split())
        if not text:
            return None
        if field.is_year:
            if not re.fullmatch(r"\d{4}", text) or not 1950 <= int(text) <= datetime.now(timezone.utc).year:
                raise MemoryDataError(f"{field.name} must be a past year, like 2024")
            return text
        code = self._code(field, text)
        if code is None:
            raise MemoryDataError(
                f"{field.name} must be one of: {', '.join(c for c, _ in self._offered(field))}")
        return code

    @staticmethod
    def _stored(field: OnboardingField, value):
        """An answer as the record stores it: a number for an integer field
        ("year_2" -> 2, "2024" -> 2024), the code otherwise."""
        if _record_schema(field).get("type") == "integer" and isinstance(value, str):
            numbered = _NUMBERED.search(value)
            return int(numbered.group(1) if numbered else value)
        return value

    def _answer(self, field: OnboardingField, stored):
        """A stored record value read back as the answer the form shows."""
        if stored in (None, "", []):
            return None
        if isinstance(stored, list):
            codes = [self._shown(field, self._code(field, s)) for s in stored if isinstance(s, str)]
            return [c for c in codes if c] or None
        if isinstance(stored, int) and not isinstance(stored, bool):
            if field.is_year:
                return str(stored)
            return next((c for c in field.choices
                         if _NUMBERED.search(c) and int(_NUMBERED.search(c).group(1)) == stored), None)
        return self._shown(field, self._code(field, stored)) if isinstance(stored, str) else None

    @staticmethod
    def _shown(field: OnboardingField, code: Optional[str]) -> Optional[str]:
        """A prefilled chip must be one the form shows: an old General Science
        group stays unpicked so the student chooses a group that is offered."""
        return code if not field.choice_list or code in field.choices else None

    def _record_prefill(self, level: OnboardingField, row) -> dict:
        """A stored record read back into the form's answers.

        An `fsc`/`ics`/`icom`/`fa` row reads as Intermediate plus its group. An
        `fsc` row with no group leaves the group unpicked, so the student has
        to choose one before continuing.
        """
        stored = _read(row, level.record_field) or ""
        if not stored:
            return {}
        answers = {level.name: _choice_code(level, stored) or stored}
        follow_ups = [f for f in FOLLOW_UPS if f.field_key == level.field_key]
        for field in follow_ups:
            mapping = field.level_by_choice or {}
            parent = (field.depends_on.get("values") or [None])[0]
            if mapping and answers[level.name] in (*mapping.values(), parent):
                options = [group for group, code in mapping.items() if code == answers[level.name]]
                group = self._answer(field, _read(row, field.record_field))
                answers[level.name] = parent
                if group and (group in options or not options):
                    answers[field.name] = group
                elif len(options) == 1:
                    answers[field.name] = options[0]
        for field in follow_ups:
            if field.name not in answers and _visible(field.depends_on, answers):
                answer = self._answer(field, _read(row, field.record_field))
                if answer:
                    answers[field.name] = answer
        return answers

    def _field_state(self, f: OnboardingField) -> dict:
        offered = self._offered(f)
        return {"name": f.name, "fieldKey": f.field_key, "required": f.required,
                "choices": [code for code, _ in offered], "isDate": f.is_date, "allowOther": f.allow_other,
                "step": f.step, "default": f.default, "options": list(f.options),
                "depends_on": f.depends_on, "multi": f.multi, "isYear": f.is_year,
                "searchable": f.searchable, "labelKey": f.label_key,
                # Catalog and study-field wording for chips the UI has no copy for.
                "labels": {code: label for code, label in offered if label != code},
                "redirects": _redirects(f)}

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
            if field.record_field and not field.depends_on:
                rows = StudentRecordService(self.db).list(str(workspace.id), field.field_key)
                if rows:
                    # A value saved before the chips were catalog codes ("o-level")
                    # reads as its code, so the chip is selected.
                    prefill.update(self._record_prefill(field, rows[0]))
        # Full name is deliberately collected here, not at signup, and is never
        # guessed from an email address or an OAuth display name.
        return {
            "required": user is not None and user.onboarded_at is None,
            "completedAt": user.onboarded_at.isoformat()
            if user is not None and user.onboarded_at else None,
            "fields": [self._field_state(f) for f in ONBOARDING_FIELDS],
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
        unknown = set(answers) - KNOWN_ANSWERS
        if unknown:
            raise MemoryDataError(f"Unknown onboarding field: {', '.join(sorted(unknown))}")

        cleaned: dict[str, Any] = {}
        for name, field in FIELDS_BY_NAME.items():
            chip = _redirect(field, answers.get(name))
            if chip:
                raise MemoryDataError(f"Choose {_chip_label(field, chip)} above")
            value = _clean(answers.get(name), field)
            if value is not None:
                cleaned[name] = value
        # Each follow-up name resolves to the one question its conditions show;
        # an answer to a hidden question (a group left from a level the student
        # changed away from) is dropped, never written.
        asked: dict[str, OnboardingField] = {}
        for field in FOLLOW_UPS:
            if field.name in asked or not _visible(field.depends_on, cleaned):
                continue
            asked[field.name] = field
            value = self._clean_follow_up(answers.get(field.name), field)
            if value is not None:
                cleaned[field.name] = value
        for name in {f.name for f in FOLLOW_UPS} - set(asked):
            cleaned.pop(name, None)
        # The current contract is the three-step form. Older in-flight clients
        # (the eight-field form, or the four-card form with a full name) still
        # complete with their own required set; their old facts are retained.
        if "firstName" in answers or "lastName" in answers:
            required = (*(f for f in ONBOARDING_FIELDS if not f.depends_on), *asked.values())
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
        writes = []  # (field, value, quote)
        records: dict[str, tuple[OnboardingField, dict, list]] = {}
        for name, value in cleaned.items():
            field = FIELDS_BY_NAME.get(name) or asked[name]
            if not field.record_field:
                writes.append((field, value, value))
                continue
            # Every answer for one record type becomes ONE record.
            main, record, quote = records.setdefault(field.field_key, (field, {}, []))
            node = record
            *parents, leaf = field.record_field.split(".")
            for part in parents:
                node = node.setdefault(part, {})
            node[leaf] = self._stored(field, value)
            if field.level_by_choice and value in field.level_by_choice:
                record[main.record_field] = field.level_by_choice[value]
            quote += [label for code in (value if isinstance(value, list) else [value])
                      for label in [dict(self._offered(field)).get(code, code)]]
        for main, record, quote in records.values():
            details = record.get("details", {})
            # A semester is kept as said; the year it falls in is what the
            # rest of PAI reads for every current student.
            if "current_semester" in details and "current_year" not in details:
                details["current_year"] = (details["current_semester"] + 1) // 2
            writes.append((main, record, " · ".join(str(q) for q in quote)))
        from .student_records import StudentRecordService
        corrects = {}
        for main, record, _ in writes:
            if not main.record_field:
                continue
            # The record the form was prefilled from, confirmed at the same
            # level (an old fsc row now Intermediate + ICS), is corrected in
            # place rather than gaining a second education record.
            rows = StudentRecordService(self.db).list(workspace_id, main.field_key)
            if rows and self._record_prefill(main, rows[0]).get(main.name) == cleaned.get(main.name):
                corrects[main.field_key] = rows[0].id

        for field, value, quote in writes:
            # A returning student's prefilled canonical answer is already
            # satisfied. Do not supersede it with an identical onboarding row
            # or erase its original provenance merely because they continued.
            if not field.record_field and existing_facts.get(field.field_key) == value:
                saved.append(field.field_key)
                continue
            student_text = value.get(field.record_field) if field.record_field else value
            candidate = MemoryCandidateService(self.db).propose(
                workspace_id=workspace_id, candidate_type="student_record" if field.record_field else "vault_fact",
                key=field.field_key, proposed_value=value, confidence=1.0,
                entities={"record_id": corrects[field.field_key]} if field.field_key in corrects else None,
                source_type="user_explicit", allow_user_explicit=True,
                input_channel="profile",
                subject_user_id=str(user.id) if user else None,
                evidence={"reason": "Stated during onboarding", "capture": "onboarding", "quote": quote,
                    **({"catalog_review": {"catalog": field.name, "status": "pending", "student_text": student_text}}
                       if field.allow_other and isinstance(student_text, str)
                       and _choice_code(field, student_text) is None else {})},
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

