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

import json
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
    # A whole number in minimum..maximum (marks, a score), or free text up to
    # max_length (grades).
    is_number: bool = False
    is_text: bool = False
    minimum: int | None = None
    maximum: int | None = None
    # The fixed values of a SEPARATE record of the same type this answer goes
    # to (the completed Matric of an Intermediate student), not the main one.
    record: dict | None = None
    # The answer this one may not exceed (marks obtained <= total marks).
    at_most: str | None = None
    # Record values written when this question is shown but left empty (a
    # test chosen with no score is planned).
    when_empty: dict | None = None
    # Required only on the first onboarding (the marks of a completed exam):
    # a student who already finished it can reopen and save without them.
    required_until_onboarded: bool = False


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
                is_year=follow["input"] == "year", label_key=follow.get("label"),
                is_number=follow["input"] == "number", is_text=follow["input"] == "text",
                max_length=follow.get("max_length", 200), minimum=follow.get("minimum"),
                maximum=follow.get("maximum"), record=follow.get("record"), at_most=follow.get("at_most"),
                when_empty=follow.get("when_empty"),
                required_until_onboarded=follow.get("required_until_onboarded", False)))
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
    if code is None and field.field_key == "education":
        # "FSc Pre-Engineering" or "BS Computer Science": a level with its
        # group or field, read the way the paths read a chat-written record.
        code = vault_catalog().read_education(text)[0]
    if code is None or code == "other":
        return None
    chip = _PARENT_CHIP.get(code, code)
    return chip if chip in field.choices else None


def _redirects(field: OnboardingField) -> dict:
    """Every normalised wording of a level -> its chip, so the form can say
    "Choose Intermediate above" on the education step instead of failing at the end."""
    if not (field.allow_other and field.choice_list and field.choices):
        return {}
    out = {}
    for choice in vault_catalog().choices(field.choice_list):
        chip = _PARENT_CHIP.get(choice.code, choice.code)
        if choice.code == "other" or chip not in field.choices:
            continue
        for wording in (choice.code, choice.label, *choice.synonyms, choice.code.replace("_", " ")):
            out[norm(wording)] = chip
    spec = vault_catalog().type(field.field_key)
    for wording, code in (spec.level_wordings if spec else {}).items():
        if _PARENT_CHIP.get(code, code) in field.choices:
            out.setdefault(wording, _PARENT_CHIP.get(code, code))
    return out
_NUMBERED = re.compile(r"_(\d+)$")
# A record's status field and the value that makes it the student's current one.
_STATUS_FIELD, _CURRENT, _COMPLETED = "academic_status", "current", "completed"


def _level(field: OnboardingField, row) -> Optional[str]:
    """A record row's level code in any wording (fsc, "BS Computer Science")."""
    catalog = vault_catalog()
    return catalog.record_level(catalog.type(field.field_key), {"qualification_name": _read(row, field.record_field)})


def _latest(rows, field: OnboardingField):
    """The record the form opens on: the most recent current one, else the
    highest level (ties: the most recent; rows arrive newest first). The
    completed Matric written beside an Intermediate answer is newer, but it
    never becomes the form's main record."""
    current = next((row for row in rows if getattr(row, _STATUS_FIELD, None) == _CURRENT), None)
    if current is not None:
        return current
    spec = vault_catalog().type(field.field_key)
    ranks = spec.level_ranks if spec else {}
    if not ranks:
        return rows[0]
    return max(enumerate(rows), key=lambda item: (ranks.get(_level(field, item[1]), -1), -item[0]))[1]


def _asked_rows(field: OnboardingField, rows):
    """The rows a main question can open on. A question with no Other box
    (the entry test) reads only rows it offers a chip for: a language test
    recorded from chat is not the entry test the form asks about."""
    if field.allow_other or not field.choices:
        return rows
    return [row for row in rows if _choice_code(field, str(_read(row, field.record_field) or "")) in field.choices]


def _separate_row(main: OnboardingField, record: dict, rows, taken=()):
    """The existing row a separate record is: the most recent one at its level."""
    level = record.get(main.record_field)
    return next((row for row in rows if row.id not in taken and _level(main, row) == level), None)


def _record_key(field: OnboardingField) -> tuple:
    """Which record an answer belongs to: its type, plus the fixed values of
    a separate record ("" for the main one)."""
    return field.field_key, json.dumps(field.record, sort_keys=True) if field.record else ""


def _put(record: dict, path: str, value) -> None:
    """Set a dotted path (details.status) in a record being built."""
    *parents, leaf = path.split(".")
    for part in parents:
        record = record.setdefault(part, {})
    record[leaf] = value


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

    def __init__(self, db, sources: Optional[dict] = None, on_saved=None):
        self.db = db
        self.vault = VaultService(db)
        # Choice lists that live outside the catalog: name -> [(code, label)].
        self.sources = sources or {}
        # Called with (workspace_id, saved keys) after the answers are written,
        # so the caller can react (PAI C re-runs the paths after an education
        # write) without app.memory importing PAI C.
        self.on_saved = on_saved

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
        if field.is_number:
            if not re.fullmatch(r"\d+", text):
                raise MemoryDataError(f"{field.name} must be a whole number")
            if not field.minimum <= int(text) <= field.maximum:
                raise MemoryDataError(f"{field.name} must be between {field.minimum} and {field.maximum}")
            return str(int(text))
        if field.is_text:
            if len(text) > field.max_length:
                raise MemoryDataError(f"{field.name} is too long")
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
        if _record_schema(field).get("type") in ("integer", "number") and isinstance(value, str):
            numbered = _NUMBERED.search(value)
            return int(numbered.group(1) if numbered else value)
        return value

    def _answer(self, field: OnboardingField, stored):
        """A stored record value read back as the answer the form shows."""
        if stored in (None, "", []):
            return None
        if field.is_number:
            if isinstance(stored, (int, float)) and not isinstance(stored, bool) and float(stored).is_integer():
                return str(int(stored))
            return stored.strip() if isinstance(stored, str) and stored.strip().isdigit() else None
        if field.is_text:
            return " ".join(stored.split()) or None if isinstance(stored, str) else None
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

    def _record_prefill(self, level: OnboardingField, row, rows=()) -> dict:
        """A stored record read back into the form's answers.

        An `fsc`/`ics`/`icom`/`fa` row reads as Intermediate plus its group. An
        `fsc` row with no group leaves the group unpicked, so the student has
        to choose one before continuing. A question about a separate record
        (the Matric marks) is read from that record's own row in `rows`.
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
                source = _separate_row(level, field.record, rows) if field.record else row
                answer = self._answer(field, _read(source, field.record_field)) if source is not None else None
                if answer:
                    answers[field.name] = answer
        return answers

    @staticmethod
    def _required(f: OnboardingField, user) -> bool:
        """Whether a question must be answered for this account now."""
        onboarded = user is not None and user.onboarded_at is not None
        return f.required and not (f.required_until_onboarded and onboarded)

    def _field_state(self, f: OnboardingField, user=None) -> dict:
        offered = self._offered(f)
        return {"name": f.name, "fieldKey": f.field_key, "required": self._required(f, user),
                "choices": [code for code, _ in offered], "isDate": f.is_date, "allowOther": f.allow_other,
                "step": f.step, "default": f.default, "options": list(f.options),
                "depends_on": f.depends_on, "multi": f.multi, "isYear": f.is_year,
                "isNumber": f.is_number, "isText": f.is_text, "atMost": f.at_most,
                "minimum": f.minimum, "maximum": f.maximum, "maxLength": f.max_length if f.is_text else None,
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
                rows = _asked_rows(field, StudentRecordService(self.db).list(str(workspace.id), field.field_key))
                if rows:
                    # A value saved before the chips were catalog codes ("o-level")
                    # reads as its code, so the chip is selected.
                    prefill.update(self._record_prefill(field, _latest(rows, field), rows))
        # Full name is deliberately collected here, not at signup, and is never
        # guessed from an email address or an OAuth display name.
        return {
            "required": user is not None and user.onboarded_at is None,
            "completedAt": user.onboarded_at.isoformat()
            if user is not None and user.onboarded_at else None,
            "fields": [self._field_state(f, user) for f in ONBOARDING_FIELDS],
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
        required_follow_ups = "firstName" in answers or "lastName" in answers
        if required_follow_ups:
            required = (*(f for f in ONBOARDING_FIELDS if not f.depends_on), *asked.values())
        elif "level" in answers:
            required = tuple(FIELDS_BY_NAME[name] for name in ("fullName", "level", "currentCity"))
        else:
            required = LEGACY_FIELDS
        user = self.owner(workspace)
        missing = [f.name for f in required if self._required(f, user) and f.name not in cleaned]
        if missing:
            raise MemoryDataError(f"Missing required answer: {', '.join(missing)}")
        # Marks obtained are always given with the total they are out of, and
        # can never be more than it.
        for field in asked.values():
            if not (field.at_most and field.name in cleaned):
                continue
            if field.at_most not in cleaned:
                raise MemoryDataError(f"Missing required answer: {field.at_most}")
            if int(cleaned[field.name]) > int(cleaned[field.at_most]):
                raise MemoryDataError(f"{field.name} cannot be more than {field.at_most}")
        # Compose split answers (first + last name) into the field they form,
        # in declared order.
        for target in {f.part_of for f in FIELDS_BY_NAME.values() if f.part_of}:
            parts = [cleaned.pop(f.name) for f in ONBOARDING_FIELDS if f.part_of == target and f.name in cleaned]
            if parts:
                cleaned[target] = " ".join(parts)

        workspace_id = str(workspace.id)
        saved, rejected = [], {}
        existing_facts = self.vault.snapshot(workspace_id, include_sensitive=True)
        writes = []  # (field, value, quote, record key)
        # Every answer for one record becomes ONE record. A question about a
        # separate record (the Matric before Intermediate) forms its own,
        # keyed by the fixed values it carries.
        records: dict[tuple, tuple[OnboardingField, dict, list]] = {}
        for name, value in cleaned.items():
            field = FIELDS_BY_NAME.get(name) or asked[name]
            if not field.record_field:
                writes.append((field, value, value, None))
                continue
            key = _record_key(field)
            main, record, quote = records.setdefault(key, (field, dict(field.record or {}), []))
            _put(record, field.record_field, self._stored(field, value))
            if field.level_by_choice and value in field.level_by_choice:
                record[main.record_field] = field.level_by_choice[value]
            quote += [label for code in (value if isinstance(value, list) else [value])
                      for label in [dict(self._offered(field)).get(code, code)]]
        for key, (main, record, quote) in records.items():
            details = record.get("details", {})
            # A semester is kept as said; the year it falls in is what the
            # rest of PAI reads for every current student.
            if "current_semester" in details and "current_year" not in details:
                details["current_year"] = (details["current_semester"] + 1) // 2
            writes.append((main, record, " · ".join(str(q) for q in quote), key))
        from .student_records import StudentRecordService
        mains = {f.field_key: f for f in FIELDS_BY_NAME.values() if f.record_field}
        corrects, targets = {}, {}
        for main, record, _, key in writes:
            if not main.record_field:
                continue
            rows = StudentRecordService(self.db).list(workspace_id, main.field_key)
            if main.record:
                # A separate record corrects the row already at its level
                # (the Matric saved last time) instead of adding another.
                taken = {t.id for k, t in targets.items() if k[0] == main.field_key}
                target = _separate_row(mains[main.field_key], record, rows, taken)
                if target is not None:
                    targets[key] = target
                    corrects[key] = {"record_id": target.id}
                continue
            # The record the form was prefilled from, confirmed at the same
            # level (an old fsc row now Intermediate + ICS), is corrected in
            # place rather than gaining a second education record.
            rows = _asked_rows(main, rows)
            if rows and self._record_prefill(main, _latest(rows, main)).get(main.name) == cleaned.get(main.name):
                targets[key] = _latest(rows, main)
                corrects[key] = {"record_id": targets[key].id}
                if required_follow_ups:
                    # Every onboarding answer of a question no longer shown
                    # (graduation year once studying, subjects once not O/A
                    # level) is cleared from the corrected record. Marks and
                    # grades are asked in either status, so a level that does
                    # not ask them never had them from onboarding: kept.
                    asked_paths = {f.record_field for f in asked.values() if not f.record}
                    record_paths = {f"{k}.{d}" for k, v in record.items() if isinstance(v, dict) for d in v}
                    record_paths |= set(record)
                    stale = {f.record_field for f in FOLLOW_UPS if f.field_key == main.field_key
                             and not (f.record or f.is_number or f.is_text)}
                    stale -= asked_paths | record_paths
                    if stale:
                        corrects[key]["clear_fields"] = sorted(stale)
        # A question shown but left empty may stand for a state (a test chosen
        # with no score is planned); once answered, that state is cleared.
        for field in asked.values():
            if not field.when_empty or _record_key(field) not in records:
                continue
            key = _record_key(field)
            record, target = records[key][1], targets.get(key)
            if field.name not in cleaned:
                if target is None or _read(target, field.record_field) in (None, ""):
                    for path, value in field.when_empty.items():
                        _put(record, path, value)
            elif target is not None:
                stale = [path for path, value in field.when_empty.items() if _read(target, path) == value]
                if stale:
                    corrects[key]["clear_fields"] = sorted({*corrects[key].get("clear_fields", ()), *stale})

        for field, value, quote, key in writes:
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
                entities=corrects.get(key),
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
                if field.record_field and isinstance(value, dict) and value.get(_STATUS_FIELD) == _CURRENT:
                    self._complete_older(workspace_id, field, result.result_id, user)
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

        if self.on_saved is not None and saved:
            self.on_saved(workspace_id, set(saved))
        return {"saved": saved, "rejected": rejected,
                "completed": bool(user and user.onboarded_at)}

    def _complete_older(self, workspace_id: str, field: OnboardingField, current_id, user) -> None:
        """A step up completes the step below: a new current record marks
        older current records of a LOWER rank completed (FSc -> Bachelor's).
        A higher one is never touched, since that would claim a credential the
        student never stated, nor another track at the same rank (DAE beside
        A-level); the paths read the most recent current record anyway. Each
        change goes through propose -> reconcile like any other answer."""
        from .student_records import StudentRecordService
        catalog = vault_catalog()
        spec = catalog.type(field.field_key)
        ranks = spec.level_ranks if spec else {}
        rows = StudentRecordService(self.db).list(workspace_id, field.field_key)

        def rank(row):
            return ranks.get(catalog.record_level(spec, {field.record_field: _read(row, field.record_field)}))

        new_rank = next((rank(row) for row in rows if row.id == current_id), None)
        if new_rank is None:
            return
        for row in rows:
            if row.id == current_id or getattr(row, _STATUS_FIELD, None) != _CURRENT:
                continue
            if rank(row) is None or rank(row) >= new_rank:
                continue
            candidate = MemoryCandidateService(self.db).propose(
                workspace_id=workspace_id, candidate_type="student_record", key=field.field_key,
                proposed_value={_STATUS_FIELD: _COMPLETED}, confidence=1.0, entities={"record_id": row.id},
                source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
                subject_user_id=str(user.id) if user else None,
                evidence={"reason": "A newer current education was stated during onboarding",
                          "capture": "onboarding", "quote": _COMPLETED})
            MemoryReconciler(self.db).reconcile(candidate)

