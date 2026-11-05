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
        "family_member", "domicile", "quota", "daily_life", "field_order", "place_preference"}
    assert catalog.type("nope") is None
    assert catalog.type("domicile").identity == []
    assert catalog.type("family_member").identity == ["relation", "name"]
    assert catalog.type("finance.budget").freshness_days == 180
    assert catalog.type("goal").freshness_days == 90
    assert catalog.type("certainty").conflict == "latest_wins"
    assert catalog.type("education").choice_fields == {
        "qualification_name": "levels", "details.awarding_body": "boards",
        "field_of_study": "intermediate_groups"}
    assert "basis" in catalog.type("strength").schema["properties"]
    assert "evidence" not in catalog.type("strength").schema["properties"]
    assert catalog.type("education").freshness_days is None
    assert [t.key for t in catalog.types(shown_on="details", storage="item")] == [
        "domicile", "quota", "field_order", "place_preference"]
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
        "matric", "o_level", "fsc", "ics", "icom", "fa", "intermediate", "a_level", "dae", "bachelor", "masters",
        "other"]


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


@pytest.mark.parametrize("follow_up, message", [
    ({"depends_on": {"field": "later"}}, "earlier answer"),
    ({"depends_on": {"field": "level", "values": []}}, "values"),
    ({"choices": "groups", "shown": ["nope"]}, "outside its choice list"),
    ({"choices": "groups", "level_by_choice": {"science": "nope"}}, "main choice list"),
    ({"choices": None}, "choices or a source"),
])
def test_bad_onboarding_follow_up_is_rejected(follow_up, message):
    from app.memory.catalog import VaultCatalog

    def catalog(**changes):
        ask = {"name": "group", "prompt": "Which group?", "input": "choice", "choices": "groups",
               "record_field": "field_of_study", "depends_on": {"field": "level", "values": ["inter"]}}
        ask = {k: v for k, v in {**ask, **changes}.items() if v is not None}
        return VaultCatalog.from_dict({
            "choices": {"levels": [_choice("inter", "Inter")], "groups": [_choice("science", "Science")]},
            "types": [{"key": "education", "storage": "record", "shown_on": "details", "inputs": ["chat"],
                       "sensitivity": "normal", "conflict": "evidence_wins", "freshness_days": None,
                       "version": 1, "onboarding": {"order": 1, "prompt": "Level?", "input": "choice",
                                                    "choices": "levels", "name": "level",
                                                    "follow_ups": [ask]}}]})

    assert catalog().type("education")
    with pytest.raises(ValueError, match=message):
        catalog(**follow_up)


def _choice(code, label, *synonyms):
    return {"code": code, "label": label, "synonyms": list(synonyms)}


def test_clashing_choice_wording_is_rejected():
    from app.memory.catalog import VaultCatalog
    clash = {"choices": {"relations": [_choice("father", "Father", "abu"), _choice("uncle", "Uncle", "Abu")]},
             "types": []}
    with pytest.raises(ValueError, match="relations.*Abu"):
        VaultCatalog.from_dict(clash)
    duplicate = {"choices": {"tests": [_choice("sat", "SAT"), _choice("sat", "SAT again")]}, "types": []}
    with pytest.raises(ValueError, match="tests"):
        VaultCatalog.from_dict(duplicate)


# -- P1-T4 task 2: field order, place preference, per-part marks ---------------

@pytest.mark.req("R-16")
def test_field_order_and_place_preference_are_catalogued_items():
    catalog = vault_catalog()
    order, place = catalog.type("field_order"), catalog.type("place_preference")
    for spec in (order, place):
        assert spec.storage == "item" and spec.identity == []
        assert set(spec.inputs) == {"chat", "details"}
        assert spec.shown_on == "details" and spec.section in {"about", "education", "money_and_place"}
    study_codes = {c.code for c in catalog.choices("study_fields")}
    validate_schema_instance(order.schema, {"fields": ["computer_science", "mbbs"]})
    validate_schema_instance(order.schema, {"fields": []})
    for bad in ({"fields": ["not_a_field"]}, {"fields": ["mbbs"] * 31}, {"fields": "mbbs"}, {}, {"fields": [], "x": 1}):
        with pytest.raises(SchemaValidationError):
            validate_schema_instance(order.schema, bad)
    assert set(order.schema["properties"]["fields"]["items"]["enum"]) == study_codes
    assert order.schema["properties"]["fields"]["maxItems"] == 30

    validate_schema_instance(place.schema, {"scope": "either", "fallback": "local_first", "regions": ["punjab"]})
    validate_schema_instance(place.schema, {"scope": "local", "fallback": "none", "regions": []})
    for bad in ({"scope": "mars"}, {"scope": "local", "fallback": "sometimes"},
                {"scope": "local", "regions": ["atlantis"]}, {"scope": "local", "regions": "punjab"},
                {"scope": "local", "extra": 1}):
        with pytest.raises(SchemaValidationError):
            validate_schema_instance(place.schema, bad)
    provinces = {c.code for c in catalog.choices("provinces")}
    assert set(place.schema["properties"]["regions"]["items"]["enum"]) == provinces


@pytest.mark.req("R-16")
def test_the_extractor_is_told_the_new_item_types():
    from app.memory.extractor import SYSTEM_PROMPT
    for key, names in (("field_order", ("fields",)), ("place_preference", ("scope", "fallback", "regions"))):
        assert f"- {key}:" in SYSTEM_PROMPT
        assert all(name in SYSTEM_PROMPT for name in names)


EDUCATION = {"qualification_name": "fsc", "academic_status": "completed"}


@pytest.mark.req("R-80")
def test_education_results_take_optional_part_marks():
    from app.memory.student_schema import validate_record
    plain = {**EDUCATION, "result": {"marks_obtained": 900, "marks_total": 1100}}
    assert validate_record("education", plain) == plain  # a total-only record stays valid
    parts = {**EDUCATION, "result": {"marks_obtained": 900, "marks_total": 1100,
                                     "part1": {"marks_obtained": 400, "marks_total": 550},
                                     "part2": {"marks_obtained": 500, "marks_total": 550}}}
    assert validate_record("education", parts) == parts
    only_part1 = {**EDUCATION, "result": {"part1": {"marks_obtained": 400, "marks_total": 550}}}
    assert validate_record("education", only_part1) == only_part1


@pytest.mark.req("R-80")
@pytest.mark.parametrize("result", [
    {"part1": {"marks_obtained": 600, "marks_total": 550}},
    {"part2": {"marks_obtained": 551, "marks_total": 550}},
    {"marks_obtained": 100, "marks_total": 1100, "part1": {"marks_obtained": 1, "marks_total": 0}},
    {"part1": {"marks_obtained": -1, "marks_total": 550}},
    {"part3": {"marks_obtained": 1, "marks_total": 2}},
    {"part1": {"marks_obtained": 1, "marks_total": 2, "grade": "A"}},
])
def test_a_part_above_its_total_is_refused(result):
    from app.memory.errors import MemoryDataError
    from app.memory.student_schema import validate_record
    with pytest.raises(MemoryDataError):
        validate_record("education", {**EDUCATION, "result": result})


@pytest.mark.req("R-80")
def test_course_score_is_not_widened_to_parts():
    from app.memory.errors import MemoryDataError
    from app.memory.student_schema import validate_record
    with pytest.raises(MemoryDataError):
        validate_record("course", {"education_id": "e", "name": "Physics",
                                   "score": {"part1": {"marks_obtained": 1, "marks_total": 2}}})
