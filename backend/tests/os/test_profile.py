"""Research profile (Slice 2 spec §4.2): per-route field definitions as data, and the reading model built from them."""
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.os.knowledge.profile import PROFILE_DIR, ProfileError, load_profile, load_profile_dir, reading_model

GERMANY = PROFILE_DIR / "germany_master.research.v1.yaml"
KEY = Path(__file__).parent / "quality" / "spike1_answer_key.yaml"


def write(tmp_path: Path, data: dict, name: str = "p.research.v1.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def germany_data() -> dict:
    return yaml.safe_load(GERMANY.read_text(encoding="utf-8"))


def test_germany_profile_loads_with_the_answer_key_fields():
    profile = load_profile(GERMANY)
    key_fields = set(next(iter(yaml.safe_load(KEY.read_text(encoding="utf-8"))["programmes"].values()))["facts"])
    assert profile.route_key == "germany_master" and profile.version == 1
    # plan ruling R2-P3: the Spike 1 key's fields, plus fields later slices added that the key does not score
    # (Slice 5: statement_requirement; the scorer skips a field the key has no value for)
    assert {f.name for f in profile.fields} == key_fields | {"statement_requirement"}
    assert set(profile.month_names) == set(range(1, 13))


def test_profile_dir_keeps_the_highest_version(tmp_path):
    data = germany_data()
    write(tmp_path, data, "a.research.v1.yaml")
    write(tmp_path, {**data, "version": 2}, "a.research.v2.yaml")
    assert load_profile_dir(tmp_path)["germany_master"].version == 2


def test_profile_dir_rejects_a_duplicate_version(tmp_path):
    data = germany_data()
    write(tmp_path, data, "a.research.v1.yaml")
    write(tmp_path, data, "b.research.v1.yaml")
    with pytest.raises(ProfileError, match="duplicate profile germany_master v1"):
        load_profile_dir(tmp_path)


def _field(data: dict, name: str) -> dict:
    return next(f for f in data["fields"] if f["name"] == name)


@pytest.mark.parametrize("mutate,msg", [
    (lambda d: _field(d, "intakes").update(type="calendar"), "type"),
    (lambda d: d["fields"].append(dict(_field(d, "intakes"))), "duplicate field 'intakes'"),
    (lambda d: _field(d, "application_route").update(values={}), "needs values"),
    (lambda d: _field(d, "english_requirement").update(scores=[]), "needs scores"),
    (lambda d: _field(d, "german_requirement").update(levels=[]), "needs levels"),
    (lambda d: _field(d, "grade_requirement").update(parts=[]), "needs parts"),
    (lambda d: d["none_phrases"].update(nonsense=["x"]), "none_phrases names unknown field 'nonsense'"),
    (lambda d: d["month_names"].pop(7), "month_names needs all 12 months"),
    (lambda d: d["official_sources"].append("https://example.org"), "domain"),
    (lambda d: d.update(colour="blue"), "colour"),
])
def test_invalid_profile_rejected(tmp_path, mutate, msg):
    data = germany_data()
    mutate(data)
    with pytest.raises(ProfileError, match=msg):
        load_profile(write(tmp_path, data))


def test_invalid_yaml_names_the_file(tmp_path):
    path = tmp_path / "bad.research.v1.yaml"
    path.write_text("key: [unclosed", encoding="utf-8")
    with pytest.raises(ProfileError, match="bad.research.v1.yaml"):
        load_profile(path)


def found(value, quote="q", url="https://www.uni-x.de/p", **extra) -> dict:
    return {"value": value, "quote": quote, "url": url, **extra}


GOOD = {
    "language_of_instruction": found("english"),
    "tuition_fee_non_eu_eur": found(0),
    "semester_contribution_eur": found(340.5, cycle="WS 2026/27"),
    "deadline_open": found("04-01"),
    "deadline_close": found("07-15", scope_quote="valid for: Master Embedded Systems"),
    "application_route": found("uni_assist"),
    "english_requirement": found({"cefr": "B2", "ielts": 6.5, "toefl_ibt": 85, "pte": 70, "moi_accepted": False}),
    "german_requirement": found({"level": "none", "when": "application"}),
    "grade_requirement": found({"german_max": 2.5, "percent_min": None}),
    "admission_test": found({"any_of": ["GRE", "GATE"]}),
    "intakes": found(["winter", "summer"]),
}


def test_reading_model_accepts_profile_values():
    Reading = reading_model(load_profile(GERMANY))
    r = Reading.model_validate(GOOD)
    assert r.application_route.value == "uni_assist" and r.english_requirement.value.ielts == 6.5
    assert Reading.model_validate({}).deadline_close is None  # every field is optional: null = not found


@pytest.mark.parametrize("field,bad", [
    ("application_route", found("agency")),
    ("deadline_close", found("7/15")),
    ("deadline_close", found("13-01")),
    ("english_requirement", found({"cefr": "B7"})),
    ("german_requirement", found({"level": "fluent"})),
    ("admission_test", found({"any_of": ["SAT"]})),
    ("intakes", found(["spring"])),
    ("intakes", found(["winter"], extra_key=1)),
    ("unknown_field", found(1)),
])
def test_reading_model_rejects_values_outside_the_profile(field, bad):
    Reading = reading_model(load_profile(GERMANY))
    with pytest.raises(ValidationError):
        Reading.model_validate({**GOOD, field: bad})


def test_reading_model_has_a_json_schema_with_hints():
    schema = reading_model(load_profile(GERMANY)).model_json_schema()
    assert "deadline_close" in schema["properties"]
    assert "non-EU" in str(schema)  # the field hints reach the model as descriptions


def test_mount_os_fails_on_invalid_profile(tmp_path):
    from fastapi import FastAPI

    from app.os.api import mount_os

    data = germany_data()
    data["fields"][0]["type"] = "calendar"
    write(tmp_path, data, "bad.research.v1.yaml")
    env = {"DATABASE_URL": "postgresql://x/y", "OS_ENABLED": "true", "OS_ADMIN_TOKEN": "t"}
    with pytest.raises(ProfileError, match="bad.research.v1.yaml"):
        mount_os(FastAPI(), env=env, profile_dir=tmp_path)


def test_worker_build_fails_on_invalid_profile(monkeypatch, tmp_path):
    from app.os.runner import worker
    from app.os.settings import load_settings

    data = germany_data()
    data["fields"][0]["type"] = "calendar"
    write(tmp_path, data, "bad.research.v1.yaml")
    monkeypatch.setattr(worker, "PROFILE_SOURCE", tmp_path)
    with pytest.raises(ProfileError, match="bad.research.v1.yaml"):
        worker.build(load_settings({"DATABASE_URL": "postgresql://x/y", "OS_WORKER_ID": "w1"}))
