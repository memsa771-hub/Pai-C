"""The Vault catalog is the one definition of every Vault type and choice list."""

import pytest

from app.memory.catalog import vault_catalog
from app.memory.student_schema import RECORD_SPECS
from app.tools.schema import validate_schema_instance, SchemaValidationError
from scripts.eval_vault import production_field_definitions

CONFLICTS = {"latest_wins", "evidence_wins", "ask_student"}
SUPPORTED_KEYWORDS = {"type", "enum", "minimum", "maximum", "minLength", "maxLength",
                      "minItems", "maxItems", "items", "properties", "required",
                      "additionalProperties"}


def _keywords(schema):
    yield from schema
    for child in schema.get("properties", {}).values():
        yield from _keywords(child)
    if isinstance(schema.get("items"), dict):
        yield from _keywords(schema["items"])


def test_every_type_is_valid():
    catalog = vault_catalog()
    types = catalog.types()
    assert {t.storage for t in types} == {"fact", "record", "item"}
    for spec in types:
        assert spec.shown_on in {"details", "story"}, spec.key
        assert spec.conflict in CONFLICTS, spec.key
        assert set(spec.inputs) <= {"chat", "document", "details", "story"} and spec.inputs, spec.key
        assert spec.freshness_days is None or spec.freshness_days > 0, spec.key
        for list_name in spec.choice_fields.values():
            assert catalog.choices(list_name), (spec.key, list_name)
    assert {t.key for t in catalog.types("record")} == {
        "education", "course", "test_attempt", "goal", "activity", "project", "achievement",
        "work_experience", "exploration_experience", "skill", "language_proficiency", "certification"}
    assert all(t.key in RECORD_SPECS for t in catalog.types("record"))
    assert {t.key for t in catalog.types("item")} == {
        "interest", "strength", "value", "pressure", "option", "myth", "certainty",
        "family_member", "domicile", "quota", "daily_life"}
    assert catalog.type("nope") is None
    assert catalog.type("domicile").identity == []
    assert catalog.type("family_member").identity == ["relation", "name"]
    assert catalog.type("finance.budget").freshness_days == 180
    assert catalog.type("goal").freshness_days == 90
    assert catalog.type("education").freshness_days is None
    assert [t.key for t in catalog.types(shown_on="details", storage="item")] == ["domicile", "quota"]
    onboarding = [t for t in types if t.onboarding]
    assert {t.onboarding["input"] for t in onboarding} <= {"text", "choice", "date"}
    assert len({t.onboarding["order"] for t in onboarding}) == len(onboarding)


def test_item_schemas_are_valid_json_schema():
    for spec in vault_catalog().types("item"):
        schema = spec.schema
        assert set(_keywords(schema)) <= SUPPORTED_KEYWORDS, spec.key
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) <= set(schema["properties"])
        assert set(spec.identity) <= set(schema["properties"])
    certainty = vault_catalog().type("certainty").schema
    validate_schema_instance(certainty, {"score": 7.5})
    for bad in ({"score": 11}, {"about": "x"}, {"score": 3, "extra": 1}):
        with pytest.raises(SchemaValidationError):
            validate_schema_instance(certainty, bad)
    pressure = vault_catalog().type("pressure").schema
    with pytest.raises(SchemaValidationError):
        validate_schema_instance(pressure, {"text": "fees", "kind": "weather"})


def test_choice_code_matches_synonyms():
    catalog = vault_catalog()
    assert catalog.choice_code("boards", "Lahore board") == "bise_lahore"
    assert catalog.choice_code("intermediate_groups", "pre eng") == "pre_engineering"
    assert catalog.choice_code("relations", "Abbu") == "father"
    assert catalog.choice_code("relations", "father") == "father"
    assert catalog.choice_code("relations", "Mother") == "mother"
    assert catalog.choice_code("relations", "martian") is None
    assert catalog.label("relations", "father") == "Father"
    assert catalog.label("relations", "unknown_code") == "unknown_code"


def test_budget_bands_exact():
    codes = [c.code for c in vault_catalog().choices("budget_bands")]
    assert codes == ["under_1_lakh", "1_3_lakh", "3_6_lakh", "6_10_lakh", "over_10_lakh", "not_sure"]
    assert [c.code for c in vault_catalog().choices("budget_covers")] == ["fees_only", "fees_and_living"]
    assert [c.code for c in vault_catalog().choices("levels")] == [
        "matric", "o_level", "fsc", "ics", "icom", "fa", "a_level", "dae", "bachelor", "other"]


def test_fact_keys_match_production_fields():
    keys = {spec["key"] for spec in production_field_definitions()}
    assert len(keys) == 24
    assert {t.key for t in vault_catalog().types("fact")} == keys


def test_bad_type_raises_value_error_naming_it():
    from app.memory.catalog import VaultCatalog
    with pytest.raises(ValueError, match="broken_type"):
        VaultCatalog.from_dict({"choices": {}, "types": [
            {"key": "broken_type", "storage": "item", "shown_on": "nowhere", "inputs": ["chat"],
             "sensitivity": "normal", "conflict": "latest_wins", "freshness_days": 1, "version": 1}]})
