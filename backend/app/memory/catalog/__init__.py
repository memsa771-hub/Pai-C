"""The Vault catalog: one file that defines every Vault type and choice list.

Why a file and not code: a new item type must work from a catalog entry alone,
so storage, display, conflict rule, freshness and schema all live in
vault_catalog.json. This module only loads and validates it. It stays free of
app imports (json + dataclasses) so any layer can read the catalog.
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

STORAGES = ("fact", "record", "item")
SHOWN_ON = ("details", "story")
INPUTS = ("chat", "document", "details", "story")
CONFLICTS = ("latest_wins", "evidence_wins", "ask_student")
ONBOARDING_INPUTS = ("text", "choice", "date")
# The JSON Schema subset app/tools/schema.validate_schema_instance understands.
SCHEMA_KEYWORDS = frozenset({
    "type", "enum", "minimum", "maximum", "minLength", "maxLength", "minItems",
    "maxItems", "items", "properties", "required", "additionalProperties"})

_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _SPACE.sub(" ", _PUNCT.sub(" ", stripped)).strip().casefold()


@dataclass(frozen=True)
class Choice:
    code: str
    label: str
    synonyms: tuple[str, ...] = ()


@dataclass(frozen=True)
class TypeSpec:
    key: str
    label: str
    storage: str
    shown_on: str
    inputs: tuple[str, ...]
    sensitivity: str
    conflict: str  # facts use their DB field definition's conflict_policy, not this
    freshness_days: int | None
    version: int
    schema: dict | None = None
    identity: list = field(default_factory=list)
    choice_fields: dict = field(default_factory=dict)
    # A record field whose list depends on the record's level, e.g. an
    # education field_of_study is a matric group, a DAE technology or a study
    # field: {field: {level code: list}}. choice_fields is the fallback.
    choice_by_level: dict = field(default_factory=dict)
    # Short level wordings ("MS", "BE") read only inside a record's own level
    # field, never in chat text where "Ms Ayesha" or "be" are everyday words:
    # {wording: level code}.
    level_wordings: dict = field(default_factory=dict)
    # How far along each level is ({level code: rank}): a new current record
    # completes only older current ones of a lower rank (FSc -> Bachelor's),
    # never a higher one or another track at the same rank (DAE beside A-level).
    level_ranks: dict = field(default_factory=dict)
    onboarding: dict | None = None
    # Which Details section shows a details type (about, education, ...).
    # Optional so older catalog files still load.
    section: str | None = None
    # Can hold a household's money (finance facts, family and pressure items):
    # the extractor's income guard covers exactly the types marked here.
    money: bool = False
    # A fact's Vault field definition (category, data_type, validation_schema,
    # policies) as production's migrations seed it; the eval and tests build
    # their field rows from this instead of copying the migrations.
    field_definition: dict | None = None


def _check_schema(schema: dict, where: str) -> None:
    if not isinstance(schema, dict):
        raise ValueError(f"{where} must be an object")
    unknown = set(schema) - SCHEMA_KEYWORDS
    if unknown:
        raise ValueError(f"unsupported schema keyword {sorted(unknown)[0]!r}")
    for name, child in schema.get("properties", {}).items():
        _check_schema(child, f"{where}.{name}")
    if "items" in schema:
        _check_schema(schema["items"], f"{where}[]")


def _check_condition(condition, asked: list[str]) -> None:
    """A `depends_on` names an answer asked before it, optionally the values
    that show it (none: any answer), and optionally a further `and`."""
    if not isinstance(condition, dict) or condition.get("field") not in asked:
        raise ValueError("onboarding depends_on must name an earlier answer")
    values = condition.get("values")
    if values is not None and (not isinstance(values, list) or not values
                               or not all(isinstance(v, str) for v in values)):
        raise ValueError("onboarding depends_on values must be a non-empty list of codes")
    if "and" in condition:
        _check_condition(condition["and"], asked)


def _check_follow_ups(onboarding: dict, choices: dict, storage: str) -> None:
    """Questions shown after the main one, each a part of the same record.

    Several may share a name (the group for Matric and the group for
    Intermediate): the student only ever sees the one whose condition holds.
    """
    follow_ups = onboarding.get("follow_ups") or []
    if follow_ups and storage != "record":
        raise ValueError("onboarding follow_ups need a record type")
    asked = [onboarding.get("name")]
    for ask in follow_ups:
        if not isinstance(ask.get("name"), str) or not ask["name"] or not ask.get("prompt"):
            raise ValueError("onboarding follow-up needs a name and a prompt")
        if ask.get("input") not in (*ONBOARDING_INPUTS, "year") or not ask.get("record_field"):
            raise ValueError("onboarding follow-up needs an input and a record_field")
        listed = ask.get("choices")
        if isinstance(listed, str):
            codes = {c.code for c in choices.get(listed, [])}
            if not codes:
                raise ValueError("onboarding follow-up uses an unknown choice list")
            if not set(ask.get("shown", ())) <= codes or not set(ask.get("level_by_choice", {})) <= codes:
                raise ValueError("onboarding follow-up names a code outside its choice list")
        elif listed is not None and not (isinstance(listed, list) and all(isinstance(c, str) for c in listed)):
            raise ValueError("onboarding follow-up choices must be a list name or a list of codes")
        if ask["input"] == "choice" and listed is None and not isinstance(ask.get("source"), str):
            raise ValueError("onboarding follow-up choice needs choices or a source")
        levels = {c.code for c in choices.get(onboarding.get("choices"), [])} \
            if isinstance(onboarding.get("choices"), str) else set()
        if not set(ask.get("level_by_choice", {}).values()) <= levels:
            raise ValueError("onboarding level_by_choice must name codes of the main choice list")
        _check_condition(ask.get("depends_on"), asked)
        asked.append(ask["name"])


def _build_type(raw: dict, choices: dict) -> TypeSpec:
    """Validate one type; any problem is reported with the type key."""
    key = raw.get("key", "<missing key>")
    try:
        storage = raw["storage"]
        if storage not in STORAGES:
            raise ValueError(f"storage must be one of {STORAGES}")
        if raw["shown_on"] not in SHOWN_ON:
            raise ValueError(f"shown_on must be one of {SHOWN_ON}")
        inputs = tuple(raw["inputs"])
        if not inputs or not set(inputs) <= set(INPUTS):
            raise ValueError(f"inputs must be a non-empty subset of {INPUTS}")
        if raw["conflict"] not in CONFLICTS:
            raise ValueError(f"conflict must be one of {CONFLICTS}")
        days = raw["freshness_days"]
        if days is not None and (not isinstance(days, int) or isinstance(days, bool) or days <= 0):
            raise ValueError("freshness_days must be a positive integer or null")
        if not isinstance(raw["version"], int) or raw["version"] < 1:
            raise ValueError("version must be a positive integer")
        schema, identity = raw.get("schema"), list(raw.get("identity", []))
        if storage == "item":
            _check_schema(schema, "schema")
            if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
                raise ValueError("item schema must be a closed object")
            props = schema.get("properties", {})
            if not set(schema.get("required", [])) <= set(props):
                raise ValueError("schema requires a field it does not define")
            if not set(identity) <= set(props):
                raise ValueError("identity names a field the schema does not define")
        choice_fields = dict(raw.get("choice_fields", {}))
        for name, list_name in choice_fields.items():
            if list_name not in choices:
                raise ValueError(f"choice field {name!r} uses unknown list {list_name!r}")
            if storage == "item" and name not in schema["properties"]:
                raise ValueError(f"choice field {name!r} is not in the schema")
        choice_by_level = dict(raw.get("choice_by_level", {}))
        for name, by_level in choice_by_level.items():
            if not isinstance(by_level, dict) or not set(by_level.values()) <= set(choices):
                raise ValueError(f"choice_by_level {name!r} uses an unknown list")
        level_wordings = {norm(w): code for w, code in dict(raw.get("level_wordings", {})).items()}
        level_list = choice_fields.get("qualification_name")
        if level_wordings and (level_list is None or not set(level_wordings.values())
                               <= {c.code for c in choices[level_list]}):
            raise ValueError("level_wordings must name codes of the qualification_name list")
        level_ranks = dict(raw.get("level_ranks", {}))
        if level_ranks and (level_list is None or not set(level_ranks) <= {c.code for c in choices[level_list]}
                            or not all(isinstance(r, int) and not isinstance(r, bool) for r in level_ranks.values())):
            raise ValueError("level_ranks must map codes of the qualification_name list to integers")
        onboarding = raw.get("onboarding")
        if onboarding is not None:
            if (not isinstance(onboarding.get("order"), int) or not onboarding.get("prompt")
                    or onboarding.get("input") not in ONBOARDING_INPUTS):
                raise ValueError("onboarding needs order, prompt and input (text|choice|date)")
            if isinstance(onboarding.get("choices"), str) and onboarding["choices"] not in choices:
                raise ValueError("onboarding uses an unknown choice list")
            # The form's own names (the frontend's answer keys) and parts.
            names = [onboarding.get("name"), *(p.get("name") for p in onboarding.get("parts", []))]
            if not all(isinstance(n, str) and n for n in names):
                raise ValueError("onboarding needs a name, and every part a name")
            if onboarding.get("shown"):
                codes = {c.code for c in choices.get(onboarding.get("choices"), [])}
                if not isinstance(onboarding.get("choices"), str) or not set(onboarding["shown"]) <= codes:
                    raise ValueError("onboarding shown choices must be codes of its choice list")
            _check_follow_ups(onboarding, choices, storage)
        money = raw.get("money", False)
        if not isinstance(money, bool):
            raise ValueError("money must be true or false")
        if storage == "fact" and key.startswith("finance.") and not money:
            # A finance fact is where a household income would land; the
            # income guard only covers types marked money.
            raise ValueError("a finance fact needs money: true")
        field_definition = raw.get("field_definition")
        if field_definition is not None:
            if storage != "fact":
                raise ValueError("only a fact has a field_definition")
            if not isinstance(field_definition, dict) or not {
                    "category", "data_type", "validation_schema"} <= set(field_definition):
                raise ValueError("field_definition needs category, data_type and validation_schema")
            if {"key", "sensitivity"} & set(field_definition):
                raise ValueError("field_definition takes key and sensitivity from the type")
        section = raw.get("section")
        if section is not None and (not isinstance(section, str) or not section.strip()):
            raise ValueError("section must be a non-empty string")
        return TypeSpec(
            key=key, label=raw.get("label", key), storage=storage, shown_on=raw["shown_on"],
            inputs=inputs, sensitivity=raw["sensitivity"], conflict=raw["conflict"],
            freshness_days=days, version=raw["version"], schema=schema, identity=identity,
            choice_fields=choice_fields, choice_by_level=choice_by_level, level_wordings=level_wordings,
            level_ranks=level_ranks, onboarding=onboarding, section=section, money=money,
            field_definition=field_definition)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        detail = f"missing {exc}" if isinstance(exc, KeyError) else str(exc)
        raise ValueError(f"Invalid catalog type {key!r}: {detail}") from exc


class VaultCatalog:
    def __init__(self, types: list[TypeSpec], choices: dict[str, list[Choice]]):
        self._types = {t.key: t for t in types}
        self._choices = choices
        self._lookup = {name: self._index(name, items) for name, items in choices.items()}

    @staticmethod
    def _index(name: str, items: list) -> dict:
        """Wording -> code for one list; the same wording for two codes is a catalog bug."""
        index: dict = {}
        codes = [c.code for c in items]
        for code in set(codes):
            if codes.count(code) > 1:
                raise ValueError(f"Invalid choice list {name!r}: code {code!r} is defined twice")
        for c in items:
            wordings = [c.code, c.label, *c.synonyms, c.code.replace("_", " ")]
            for text in wordings:
                seen = index.setdefault(norm(text), c.code)
                if seen != c.code:
                    raise ValueError(
                        f"Invalid choice list {name!r}: {text!r} maps to both {seen!r} and {c.code!r}")
        return index

    @classmethod
    def from_dict(cls, data: dict) -> "VaultCatalog":
        choices = {name: [Choice(c["code"], c["label"], tuple(c.get("synonyms", ()))) for c in items]
                   for name, items in data.get("choices", {}).items()}
        types = [_build_type(raw, choices) for raw in data.get("types", [])]
        keys = [t.key for t in types]
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"Invalid catalog type {sorted(dupes)[0]!r}: defined twice")
        return cls(types, choices)

    def type(self, key: str) -> TypeSpec | None:
        return self._types.get(key)

    def types(self, storage: str | None = None, shown_on: str | None = None) -> list[TypeSpec]:
        return [t for t in self._types.values()
                if (storage is None or t.storage == storage)
                and (shown_on is None or t.shown_on == shown_on)]

    def choice_names(self) -> list[str]:
        return list(self._choices)

    def choices(self, name: str) -> list[Choice]:
        return list(self._choices.get(name, ()))

    def choice_code(self, name: str, text: str) -> str | None:
        """Code for the wording a student used (code, label or synonym), or None."""
        return self._lookup.get(name, {}).get(norm(text))

    def label(self, name: str, code: str) -> str:
        for c in self._choices.get(name, ()):
            if c.code == code:
                return c.label
        return code

    def record_choice_fields(self, spec: TypeSpec | None, value) -> dict:
        """field path -> choice list for one record: a field whose list depends
        on the record's level (choice_by_level) reads that level's list, so a
        Bachelor's field_of_study is a study field and never an intermediate
        group. Every reader (display, normalize, the Details editor, paths)
        resolves the lists here."""
        if spec is None:
            return {}
        lists = dict(spec.choice_fields)
        if spec.choice_by_level and isinstance(value, dict):
            level = self.record_level(spec, value)
            for path, by_level in spec.choice_by_level.items():
                if level in by_level:
                    lists[path] = by_level[level]
        return lists

    def record_level(self, spec: TypeSpec | None, value) -> str | None:
        """A record's level code in any wording: the code or a synonym, else
        (for an education record) the level an older row's title names, so
        "BS" or "BS Computer Science" reads as bachelor."""
        if spec is None or not isinstance(value, dict):
            return None
        text = str(value.get("qualification_name") or "")
        level = self.choice_code(spec.choice_fields.get("qualification_name", "levels"), text)
        if level is None and spec.key == "education" and text:
            level = self.read_education(text)[0]
        return level

    def read_education(self, qualification, field=None) -> tuple[str | None, str | None]:
        """(level code, group/technology/field code) for an education record in
        any wording, or None where it names none.

        Chat, documents and Other often store the whole thing in one string
        ("FSc Pre-Engineering", "BS Computer Science") or a field outside the
        level's list ("Intermediate" + "Computer Science"). Read in this order:
        the level and field as given; both together as one level wording
        ("intermediate computer science" is ICS); a level prefix followed by
        the field, trying each tail of the remainder so "Bachelor of Science in
        Computer Science" still finds Computer Science. Only catalog wordings
        decide, so a new synonym is a data change.
        """
        q, f = norm(str(qualification or "")), norm(str(field or ""))
        spec = self.type("education")

        def level_of(text):
            code = (self.choice_code("levels", text) or spec.level_wordings.get(text)) if text else None
            return None if code == "other" else code

        def field_of(level, text):
            if not text:
                return None
            list_name = self.record_choice_fields(spec, {"qualification_name": level}).get("field_of_study")
            return self.choice_code(list_name, text) if list_name else None

        level = level_of(q)
        if level and (not f or field_of(level, f)):
            return level, field_of(level, f)
        words = f"{q} {f}".split()
        if f and level_of(" ".join(words)):
            return level_of(" ".join(words)), None
        fallback = level
        for cut in range(len(words) - 1, 0, -1):
            prefix = level_of(" ".join(words[:cut]))
            if prefix is None:
                continue
            for start in range(cut, len(words)):
                code = field_of(prefix, " ".join(words[start:]))
                if code:
                    return prefix, code
            fallback = fallback or prefix
        return fallback, None


@lru_cache(maxsize=1)
def vault_catalog() -> VaultCatalog:
    path = Path(__file__).with_name("vault_catalog.json")
    return VaultCatalog.from_dict(json.loads(path.read_text(encoding="utf-8")))
