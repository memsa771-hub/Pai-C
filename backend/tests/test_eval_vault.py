"""Vault golden set: case integrity, facet mapping, scoring and the offline harness."""
import json

import pytest

from scripts import eval_vault
from scripts.eval import vault_golden


def test_every_case_is_valid_synthetic_and_covers_each_language():
    cases = vault_golden.load_cases()
    assert len(cases) >= 25
    by_language = {lang: [c for c in cases if c["language"] == lang] for lang in vault_golden.LANGUAGES}
    assert all(len(group) >= 4 for group in by_language.values()), {k: len(v) for k, v in by_language.items()}
    assert all(case["synthetic"] is True for case in cases)
    core = {item["facet"] for case in cases for item in case["expected"]
            if vault_golden.FACETS[item["facet"]] == "core"}
    assert {"education", "city", "budget", "family_member", "test", "mobility", "domicile", "quota"} <= core


def test_invalid_cases_are_refused():
    base = {"id": "x", "language": "en", "synthetic": True, "turns": ["hi"],
            "expected": [{"facet": "city", "match": {"value": "Lahore"}}]}
    vault_golden.validate_case(base)
    for change, reason in [({"language": "fr"}, "language"), ({"synthetic": False}, "synthetic"),
                           ({"turns": []}, "turns"), ({"expected": [{"facet": "colour", "match": {}}]}, "facet"),
                           ({"must_not": [{"facet": "goal", "match": {"text": "x"}}]}, "why"),
                           ({"expected": [{"facet": "city", "match": {"value": {"weird": 1}}}]}, "spec")]:
        with pytest.raises(ValueError, match=reason):
            vault_golden.validate_case({**base, **change})


@pytest.mark.parametrize("spec,observed,ok", [
    ("pre engineering", "FSc Pre-Engineering", True),
    (["ics", "computer"], "Computer Science", True),
    ({"all": ["cricket", "tournament"]}, "Organized a school cricket tournament", True),
    ({"all": ["cricket", "tournament"]}, "Plays cricket", False),
    ({"num": 92.0, "tol": 0.1}, 92.0, True),
    ({"num": 85}, "87", False),
    ({"between": [200000, 300000]}, 250000, True),
    ({"one_of": [25000, 300000]}, 300000, True),
    ("Lahore", None, False),
])
def test_spec_matching(spec, observed, ok):
    assert vault_golden.spec_matches(spec, observed) is ok


def test_facets_from_profile_maps_todays_vault():
    profile = {
        "facts": {"identity.preferred_name": "Bilal", "location.current_city": "Lahore",
                  "finance.budget": {"amount": 250000, "currency": "PKR", "period": "per_year"},
                  "preferences.location_limits": ["Gujranwala only"]},
        "records": {
            "education": [{"qualification_name": "FSc", "canonical_level": "upper_secondary",
                           "field_of_study": "Pre-Engineering", "details": {"awarding_body": "BISE Lahore"},
                           "result": {"marks_obtained": 1012, "marks_total": 1100}}],
            "test_attempt": [{"test_type": "MDCAT", "overall_score": "140"}],
            "activity": [{"title": "Organized a school cricket tournament", "id": "a1"}],
            "external_influence": [{"influencer_type": "father", "suggested_direction": "Electrical engineering"}],
        },
    }
    facets = vault_golden.facets_from_profile(profile)
    by_name = {f["facet"]: f for f in facets}
    assert by_name["education"]["marks"] == 92.0
    assert vault_golden.facet_matches({"board": "Lahore", "group": "pre engineering"}, by_name["education"])
    assert vault_golden.facet_matches({"amount": {"between": [200000, 300000]}, "period": "year"}, by_name["budget"])
    assert vault_golden.facet_matches({"text": "Gujranwala"}, by_name["mobility"])
    assert vault_golden.facet_matches({"name": "MDCAT", "score": {"num": 140}}, by_name["test"])
    assert vault_golden.facet_matches({"text": {"all": ["cricket", "tournament"]}}, by_name["experience"])
    assert "a1" not in by_name["experience"]["text"]
    assert vault_golden.facet_matches({"text": {"all": ["father", "engineering"]}}, by_name["family_member"])


@pytest.mark.parametrize("text,flagged", [
    ("Organized a school cricket tournament", False),
    ("Zainab Ali", False),
    ("عائشہ خان", True),
    ("mujhe cricket acha lagta hai", True),
])
def test_not_english_flags_untranslated_values(text, flagged):
    assert vault_golden.not_english({"text": text}) is flagged


def test_scoring_counts_recall_and_must_not_violations():
    case = {"id": "c", "language": "en",
            "expected": [{"facet": "education", "match": {"marks": {"num": 87}}},
                         {"facet": "city", "match": {"value": "Lahore"}}],
            "must_not": [{"facet": "education", "match": {"marks": {"num": 85}}, "why": "corrected"}]}
    facets = [{"facet": "education", "marks": 85.0, "text": "85"}]
    result = vault_golden.score_case(case, facets)
    assert [item["found"] for item in result["expected"]] == [False, False]
    assert result["must_not_violations"] == [{"facet": "education", "why": "corrected"}]
    summary = vault_golden.summarize([result])
    assert summary["overall"] == {"found": 0, "expected": 2, "recall": 0.0}
    assert summary["must_not_violations"] == 1


def test_production_fields_match_the_migrations():
    specs = eval_vault.production_field_definitions()
    keys = {spec["key"] for spec in specs}
    assert len(specs) == len(keys) == 24
    assert {"location.current_city", "finance.budget", "preferences.location_limits"} <= keys
    by_key = {spec["key"]: spec for spec in specs}
    assert by_key["mobility.relocation_willingness"]["source_policy"]["allowed_sources"] == ["user_explicit", "conversation"]
    assert by_key["location.current_city"]["source_policy"] == {"temporal_change": "student_transition"}
    assert "source_policy" not in by_key["preferences.location_limits"]


@pytest.mark.asyncio
async def test_harness_runs_the_real_pipeline_offline_with_a_fake_model():
    case = next(c for c in vault_golden.load_cases() if c["id"] == "ru-fsc-cricket")
    outputs = [
        {"candidates": [
            {"candidate_type": "vault_fact", "operation": "upsert", "key": "identity.preferred_name",
             "proposed_value": "Bilal", "quote": "Mera naam Bilal hai", "confidence": 0.95},
            {"candidate_type": "vault_fact", "operation": "upsert", "key": "location.current_city",
             "proposed_value": "Lahore", "quote": "main Lahore mein rehta hoon", "confidence": 0.95}]},
        {"candidates": [
            {"candidate_type": "student_record", "operation": "upsert", "key": "education",
             "proposed_value": {"qualification_name": "FSc", "canonical_level": "upper_secondary",
                                "field_of_study": "Pre-Engineering", "academic_status": "completed",
                                "details": {"awarding_body": "BISE Lahore"}, "result": {"percentage": 85}},
             "quote": "FSc pre-engineering Lahore board se 85%", "confidence": 0.9},
            # Must be dropped: the quote is not in the student's message.
            {"candidate_type": "vault_fact", "operation": "upsert", "key": "location.current_city",
             "proposed_value": "Karachi", "quote": "I live in Karachi", "confidence": 0.9}]},
        {"candidates": []},
    ]

    async def fake_model(case_id, turn_index, kwargs):
        assert case_id == "ru-fsc-cricket"
        assert case["turns"][turn_index] in kwargs["messages"][0]["content"]
        return json.dumps(outputs[turn_index])

    result = await eval_vault.run_case(case, fake_model)
    found = {item["facet"]: item["found"] for item in result["expected"]}
    assert found == {"name": True, "city": True, "education": True, "experience": False}
    assert result["must_not_violations"] == [] and result["not_english"] == []
    assert any("quote" in reason for reason in result["extractor_drops"])
    assert result["accepted_without_quote"] == 0


@pytest.mark.asyncio
async def test_recorded_mode_reports_missing_and_stale_recordings(tmp_path, monkeypatch):
    monkeypatch.setattr(eval_vault, "RECORDINGS", tmp_path)
    case = next(c for c in vault_golden.load_cases() if c["id"] == "en-marks-correction")
    (tmp_path / "en-marks-correction.json").write_text(json.dumps(
        {"prompt_fingerprint": "old", "outputs": ["{}", "{}"]}))
    report = await eval_vault.evaluate([case], eval_vault.recorded_model("new"))
    assert report["skipped"] == [{"id": "en-marks-correction", "reason": "stale_recording"}]
    other = next(c for c in vault_golden.load_cases() if c["id"] == "ru-budget-range")
    report = await eval_vault.evaluate([other], eval_vault.recorded_model("new"))
    assert report["skipped"] == [{"id": "ru-budget-range", "reason": "not_recorded"}]


def test_report_is_written_in_json_and_markdown(tmp_path):
    result = vault_golden.score_case(
        {"id": "c", "language": "ur", "expected": [{"facet": "city", "match": {"value": "Karachi"}}]},
        [{"facet": "city", "value": "کراچی", "text": "کراچی"}])
    report = {"mode": "recorded", "summary": vault_golden.summarize([dict(result, extractor_drops=[])]),
              "skipped": [], "cases": [dict(result, extractor_drops=["quote not found"])]}
    path = eval_vault.write_report(report, tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "Not English: کراچی" in text and "Missed: city" in text
    assert json.loads((tmp_path / "vault_eval.json").read_text(encoding="utf-8"))["mode"] == "recorded"
