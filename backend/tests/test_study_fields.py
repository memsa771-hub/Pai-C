"""Study fields are real fields of study, each tied to the groups that open it."""

import re

import pytest

from app.memory.catalog import vault_catalog
from app.pai_c.paths.fields import fields_for_group, known_groups, student_groups, study_fields
from app.pai_c.policy.controller import load_data

FAMILIES_REQUIRED = {"engineering", "computing", "health", "business", "sciences",
                     "arts_humanities", "law", "architecture_design"}


def _titles(fields):
    return {f.title for f in fields}


def test_every_field_has_a_valid_isced_code_and_known_groups():
    isced = load_data("fields_of_study.json")["fields"]
    groups = known_groups()
    fields = study_fields()
    for key, field in fields.items():
        assert field.key == key
        assert field.title and field.family and field.levels, key
        assert field.isced in isced, key
        assert field.open_to, key
        assert set(field.open_to) <= groups, key
        assert set(field.check) <= groups, key
        assert not set(field.open_to) & set(field.check), key


def test_known_groups_are_the_catalog_intermediate_groups_plus_dae():
    catalog_groups = {c.code for c in vault_catalog().choices("intermediate_groups")}
    assert known_groups() == catalog_groups | {"dae"}


def test_enough_real_fields_across_families():
    fields = study_fields()
    assert len(fields) >= 40
    assert FAMILIES_REQUIRED <= {f.family for f in fields.values()}
    titles = _titles(fields.values())
    for title in ("Electrical Engineering", "Computer Engineering", "Software Engineering",
                  "Computer Science", "MBBS (Medicine)", "Pharm-D (Pharmacy)", "BBA",
                  "Architecture", "Law (LLB)"):
        assert title in titles
    assert len(titles) == len(fields)  # titles are what the student sees; no two alike


def test_pre_medical_opens_mbbs_not_mechanical_engineering():
    open_, check = fields_for_group("pre_medical")
    assert "MBBS (Medicine)" in _titles(open_)
    assert "Mechanical Engineering" not in _titles(open_)


def test_ics_opens_computer_science_and_checks_some_engineering():
    open_, check = fields_for_group("ics")
    assert "Computer Science" in _titles(open_)
    assert any(f.family == "engineering" for f in check)
    assert all(f.check_note for f in check)


def test_unknown_group_opens_nothing():
    assert fields_for_group("astrology") == ([], [])


@pytest.mark.parametrize("record, group", [
    ({"qualification_name": "fsc", "field_of_study": "pre_engineering"}, "pre_engineering"),
    ({"qualification_name": "fsc", "field_of_study": "pre_medical"}, "pre_medical"),
    ({"qualification_name": "fsc", "field_of_study": "general_science"}, "general_science"),
    ({"qualification_name": "FSc", "field_of_study": "Pre-Medical"}, "pre_medical"),
    ({"qualification_name": "ics"}, "ics"),
    ({"qualification_name": "icom"}, "icom"),
    ({"qualification_name": "fa"}, "fa_humanities"),
    ({"qualification_name": "intermediate", "field_of_study": "icom"}, "icom"),
    ({"qualification_name": "dae", "field_of_study": "electrical"}, "dae"),
    ({"qualification_name": "fsc"}, None),
    ({"qualification_name": "intermediate"}, None),
    ({"qualification_name": "matric", "field_of_study": "science_biology"}, None),
    ({"qualification_name": "bachelor", "field_of_study": "bba"}, None),
    ({}, None),
])
def test_student_groups_from_the_education_record(record, group):
    assert student_groups(record) == ({group} if group else set())


def test_student_groups_cover_every_intermediate_group():
    for code in {c.code for c in vault_catalog().choices("intermediate_groups")}:
        assert student_groups({"qualification_name": "intermediate", "field_of_study": code}) == {code}


@pytest.mark.parametrize("level, subjects, group", [
    ("a_level", ["physics", "mathematics", "chemistry"], "pre_engineering"),
    ("a_level", ["Biology", "Chemistry", "Physics"], "pre_medical"),
    ("a_level", ["mathematics", "physics", "computer_science"], "ics"),
    ("a_level", ["accounting", "business", "economics"], "icom"),
    ("a_level", ["sociology", "history", "english_literature"], "fa_humanities"),
    ("o_level", ["biology", "chemistry", "physics", "mathematics"], "pre_medical|pre_engineering"),
    ("a_level", [], None),
])
def test_student_groups_from_subjects_follow_the_data_rule(level, subjects, group):
    expected = set(group.split("|")) if group else set()
    assert student_groups({"qualification_name": level, "subjects": subjects}) == expected
    assert student_groups({"qualification_name": level, "details": {"subjects": subjects}}) == expected


def test_subject_rules_use_catalog_subject_codes_and_known_groups():
    catalog = vault_catalog()
    rules = load_data("study_fields.json")["group_rules"]
    for level, rows in rules["subject_rules"].items():
        codes = {c.code for c in catalog.choices(f"{level}_subjects")}
        assert codes, level
        for row in rows:
            assert row["group"] in known_groups()
            assert set(row.get("all", [])) | set(row.get("any", [])) <= codes, row


def test_catalog_has_the_onboarding_education_lists():
    catalog = vault_catalog()
    levels = {c.code for c in catalog.choices("levels")}
    assert {"matric", "o_level", "fsc", "ics", "icom", "fa", "a_level", "intermediate", "dae",
            "bachelor", "masters", "other"} <= levels
    assert {c.code for c in catalog.choices("matric_groups")} == {
        "science_biology", "science_computer", "arts"}
    for name in ("o_level_subjects", "a_level_subjects", "dae_technologies"):
        assert len(catalog.choices(name)) >= 5, name
    assert catalog.choice_code("levels", "Intermediate") == "intermediate"
    assert catalog.choice_code("levels", "HSSC") == "fsc"  # existing wordings keep their codes
    assert catalog.choice_code("a_level_subjects", "Maths") == "mathematics"


@pytest.mark.parametrize("group, closed_families", [
    ("icom", {"health", "engineering"}),
    ("fa_humanities", {"health", "engineering"}),
    ("ics", {"health"}),
])
def test_groups_do_not_open_fields_they_cannot_enter(group, closed_families):
    open_, _ = fields_for_group(group)
    assert not [f.title for f in open_ if f.family in closed_families]


def test_every_check_has_a_note():
    assert not [f.key for f in study_fields().values() if f.check and not f.check_note.strip()]


GROUP_WORDS = {"ics": "ICS", "icom": "I.Com", "pre_medical": "Pre-Medical", "pre_engineering": "Pre-Engineering",
               "fa_humanities": "FA", "general_science": "General Science", "dae": "DAE"}


def test_engineering_check_notes_name_only_their_own_check_groups():
    for field in study_fields().values():
        if field.family != "engineering":
            continue
        named = {code for code, word in GROUP_WORDS.items()
                 if re.search(rf"(?<![\w.-]){re.escape(word)}(?![\w-])", field.check_note)}
        assert named <= set(field.check), field.key


def test_architecture_does_not_check_fa():
    assert "fa_humanities" not in study_fields()["architecture"].check


def test_round_two_fields_are_present():
    titles = _titles(study_fields().values())
    for title in ("Mining Engineering", "Geological Engineering", "Automotive Engineering", "Geography",
                  "Philosophy", "Public Health", "Management Sciences / HRM", "Actuarial Science",
                  "Aviation Management", "Anesthesia / Operation Theatre Technology"):
        assert title in titles


def test_masters_wordings_do_not_catch_everyday_words():
    from app.memory.vault_context import turn_words
    catalog = vault_catalog()
    for text in ("Ms", "master", "ma", "MA"):
        assert catalog.choice_code("levels", text) is None, text
    assert catalog.choice_code("levels", "MPhil") == "masters"
    assert "master" not in turn_words("Ms Ayesha ne kaha ma bhi aaungi")


def test_catalog_study_field_labels_mirror_the_policy_file():
    """The Details page labels a degree's field from the catalog; it must say
    exactly what the study fields say."""
    assert [(c.code, c.label) for c in vault_catalog().choices("study_fields")] == [
        (f.key, f.title) for f in study_fields().values()]
