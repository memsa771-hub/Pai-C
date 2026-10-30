"""The Spike 1 answer key is a permanent quality set (parent spec §5): keep it well-formed."""
from pathlib import Path

import pytest
import yaml

KEY = Path(__file__).parent / "quality" / "spike1_answer_key.yaml"
FIELDS = {
    "language_of_instruction", "tuition_fee_non_eu_eur", "semester_contribution_eur",
    "deadline_open", "deadline_close", "application_route", "english_requirement",
    "german_requirement", "grade_requirement", "admission_test", "intakes",
}
ROUTES = {None, "uni_assist", "uni_assist_vpd", "direct"}
LANGUAGES = {None, "english", "english_or_german", "mostly_english"}
STATUSES = {"confirmed", "needs_followup", "conflict", "excluded"}


@pytest.fixture(scope="module")
def programmes() -> dict:
    return yaml.safe_load(KEY.read_text(encoding="utf-8"))["programmes"]


def test_thirty_rows_each_once(programmes):
    assert sorted(p["row"] for p in programmes.values()) == list(range(1, 31))


@pytest.mark.parametrize("field", ["university", "programme", "cycle", "key_status", "sources", "facts"])
def test_every_programme_has(programmes, field):
    assert all(p.get(field) for p in programmes.values()), field


def test_facts_have_exactly_the_scored_fields(programmes):
    for ref, p in programmes.items():
        assert set(p["facts"]) == FIELDS, ref
        assert set(p.get("open_fields", [])) <= FIELDS, ref


def test_enums_and_shapes(programmes):
    for ref, p in programmes.items():
        f = p["facts"]
        assert p["key_status"] in STATUSES, ref
        assert f["application_route"] in ROUTES, ref
        assert f["language_of_instruction"] in LANGUAGES, ref
        assert f["intakes"] is None or (set(f["intakes"]) <= {"winter", "summer"} and "winter" in f["intakes"]), ref
        for d in ("deadline_open", "deadline_close"):
            v = f[d]
            assert v is None or (len(v) == 5 and v[2] == "-" and 1 <= int(v[:2]) <= 12 and 1 <= int(v[3:]) <= 31), (ref, d)
        assert all(u.startswith("https://") for u in p["sources"]), ref


def test_seeded_programmes_agree_with_the_key(programmes):
    seed_path = Path(__file__).parents[2] / "app" / "os" / "knowledge" / "seed" / "germany_ws2027.yaml"
    seed = yaml.safe_load(seed_path.read_text(encoding="utf-8"))["programmes"]
    for ref, facts in seed.items():
        key = programmes[ref]["facts"]
        assert facts["deadline_close"]["value"]["date"][5:] == key["deadline_close"], ref
        assert facts["application_route"]["value"] == key["application_route"], ref
