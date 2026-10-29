"""Document types as data (Slice 3 spec S3-D2, invariant 12).

Each type is one YAML file in `types/` (`<key>.v<version>.yaml`): its fields with a generic type, the fields that
take part in cross-checks, and the rules between fields. Python knows only the generic types, so a new document
type is a new file. The reading model the reader fills is built from the type with `pydantic.create_model`.
"""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, model_validator

TYPES_DIR = Path(__file__).parent / "types"

GenericType = Literal["text", "name", "date", "number", "grade", "band", "code", "mrz_line", "enum"]
CrossCheck = Literal["full_name", "father_name", "date_of_birth"]
_RULE_ARITY = {"lte": 2, "mrz": 5}


class DocumentTypeError(ValueError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FieldSpec(_Model):
    name: str
    type: GenericType
    hint: str
    label: str | None = None  # the student's plain label, when the name alone is technical (Slice 9 Task 11)
    required: bool = False
    pattern: str | None = None  # `code`: the value must match
    values: list[str] = []  # `enum`: the allowed values
    cross_check: CrossCheck | None = None

    @model_validator(mode="after")
    def _type_needs(self) -> "FieldSpec":
        if self.type == "enum" and not self.values:
            raise ValueError(f"field '{self.name}' (enum) needs values")
        return self


class Rule(_Model):
    """`band_mean`: the last field equals the band-rounded mean of the others. `lte`: first <= second.
    `mrz`: [line1, line2, document number, date of birth, expiry date] agree and pass their check digits."""

    kind: Literal["band_mean", "lte", "mrz"]
    fields: list[str]

    @model_validator(mode="after")
    def _arity(self) -> "Rule":
        want = _RULE_ARITY.get(self.kind)
        if want is not None and len(self.fields) != want:
            raise ValueError(f"rule {self.kind} needs {want} fields, got {self.fields}")
        if self.kind == "band_mean" and len(self.fields) < 3:
            raise ValueError("rule band_mean needs at least 2 parts and the total")
        return self


class DocumentType(_Model):
    key: str
    version: int = Field(ge=1)
    label: str
    fields: list[FieldSpec]
    rules: list[Rule] = []
    full_name_from: list[str] = []  # the cross-check name, built from parts (e.g. given names + surname)

    @model_validator(mode="after")
    def _consistent(self) -> "DocumentType":
        names = [f.name for f in self.fields]
        for n in names:
            if names.count(n) > 1:
                raise ValueError(f"duplicate field '{n}'")
        for ref in [f for r in self.rules for f in r.fields] + self.full_name_from:
            if ref not in names:
                raise ValueError(f"unknown field '{ref}'")
        return self

    def field(self, name: str) -> FieldSpec:
        return next(f for f in self.fields if f.name == name)


def _readable(raw: Any, e: ValidationError) -> str:
    """Each error with the field it is about named, e.g. "field 'issue_date' (type): Input should be ..."."""
    raw_fields = raw.get("fields") if isinstance(raw, dict) else None
    parts = []
    for err in e.errors():
        loc, where = list(err["loc"]), ""
        if len(loc) >= 2 and loc[0] == "fields" and isinstance(loc[1], int) and isinstance(raw_fields, list) \
                and loc[1] < len(raw_fields) and isinstance(raw_fields[loc[1]], dict):
            name = raw_fields[loc[1]].get("name", f"#{loc[1]}")
            where = f"field '{name}'" + (f" ({'.'.join(map(str, loc[2:]))})" if loc[2:] else "") + ": "
        elif loc:
            where = f"{'.'.join(map(str, loc))}: "
        parts.append(where + err["msg"])
    return "; ".join(parts)


def load_document_type(path: Path) -> DocumentType:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DocumentTypeError(f"{path.name}: invalid YAML: {e}") from e
    try:
        return DocumentType.model_validate(raw)
    except ValidationError as e:
        raise DocumentTypeError(f"{path.name}: {_readable(raw, e)}") from e


def load_document_types(directory: Path = TYPES_DIR) -> dict[str, DocumentType]:
    """The newest version of each type. An invalid file stops startup, naming the file and the field."""
    newest: dict[str, DocumentType] = {}
    for path in sorted(directory.glob("*.v*.yaml")):
        t = load_document_type(path)
        if t.key not in newest or t.version > newest[t.key].version:
            newest[t.key] = t
    return newest


_FORBID = ConfigDict(extra="forbid")


def _python_type(spec: FieldSpec) -> Any:
    if spec.type in ("number", "grade", "band"):
        return float
    if spec.type == "enum":
        return Literal[tuple(spec.values)]
    return str  # text, name, code, mrz_line, and date (kept as read; the validators judge it)


def reading_model(t: DocumentType) -> type[BaseModel]:
    """One reading of one document: every field optional (None = the document does not show it), plus the
    type the reader thinks the document is."""
    fields: dict[str, Any] = {f.name: (_python_type(f) | None, Field(None, description=f.hint)) for f in t.fields}
    fields["detected_type"] = (str | None, Field(None, description="What kind of document this is"))
    return create_model(f"Reading_{t.key}_v{t.version}", __config__=_FORBID, **fields)
