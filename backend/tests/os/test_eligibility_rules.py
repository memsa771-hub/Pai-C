"""Slice 4 Task 1: eligibility rules live in each route's playbook (spec S4-D2). Python knows only the generic parts."""

from pathlib import Path

import pytest
import yaml

from app.os.documents.types import load_document_types
from app.os.eligibility.rules import EligibilityRules, check_rules, profile_keys
from app.os.knowledge.profile import load_profile_dir
from app.os.playbooks import PLAYBOOK_DIR, PlaybookError, load_playbook, load_playbook_dir

FAKE_DIR = Path(__file__).parent / "playbooks"
TYPES = load_document_types()
KEYS = profile_keys(TYPES)
GERMANY_FACTS = {f.name for f in load_profile_dir()["germany_master"].fields}
FAKE_KEYS = KEYS | {"entry_test.score"}  # no entry-test document type yet; the fake route still names one


def _germany():
    return load_playbook_dir(PLAYBOOK_DIR)[("germany_master", 1)]


def test_all_playbooks_load_with_rules():
    germany = _germany()
    assert germany.eligibility.grade[0].method == "linear_scale"
    assert germany.eligibility.grade[1].method == "threshold"
    assert germany.self_serve.choose_task == "choose_programmes"
    check_rules(germany, GERMANY_FACTS, KEYS)
    fakes = load_playbook_dir(FAKE_DIR)
    ireland, pk = fakes[("ireland_master", 1)], fakes[("pakistan_bs", 1)]
    assert [g.method for g in ireland.eligibility.grade] == ["threshold"]
    assert [g.method for g in pk.eligibility.grade] == ["weighted_aggregate"]
    assert pk.eligibility.test is not None and ireland.self_serve is None
    for book in (ireland, pk):
        check_rules(book, None, FAKE_KEYS)  # fake routes have no research profile


def _with(tmp_path: Path, change) -> Path:
    data = yaml.safe_load((PLAYBOOK_DIR / "germany_master.v1.yaml").read_text(encoding="utf-8"))
    change(data["eligibility"])
    p = tmp_path / "germany_master.v1.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return p


def test_unknown_fact_named_at_load(tmp_path):
    book = load_playbook(_with(tmp_path, lambda e: e["grade"][0].update(requirement="grade_minimum")))
    with pytest.raises(PlaybookError, match="germany_master.*grade_minimum"):
        check_rules(book, GERMANY_FACTS, KEYS)


def test_unknown_profile_key_named_at_load(tmp_path):
    book = load_playbook(_with(tmp_path, lambda e: e["grade_scales"]["cgpa_4"].update(value="transcript.gpa")))
    with pytest.raises(PlaybookError, match="germany_master.*transcript.gpa"):
        check_rules(book, GERMANY_FACTS, KEYS)


def test_unknown_method_refused(tmp_path):
    with pytest.raises(PlaybookError, match="method"):
        load_playbook(_with(tmp_path, lambda e: e["grade"][0].update(method="lookup_table")))


def test_grade_check_needs_its_method_inputs(tmp_path):
    with pytest.raises(PlaybookError, match="target"):
        load_playbook(_with(tmp_path, lambda e: e["grade"][0].pop("target")))


def test_playbook_without_rules_still_loads(tmp_path):
    data = yaml.safe_load((PLAYBOOK_DIR / "germany_master.v1.yaml").read_text(encoding="utf-8"))
    data.pop("eligibility"), data.pop("self_serve")
    p = tmp_path / "germany_master.v1.yaml"
    p.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    book = load_playbook(p)
    assert book.eligibility is None and book.self_serve is None
    check_rules(book, GERMANY_FACTS, KEYS)


def test_profile_keys_are_doc_type_and_field():
    assert {"transcript.cgpa", "ielts_trf.overall", "min_passing_grade_letter.min_pass"} - KEYS == \
        {"min_passing_grade_letter.min_pass"}  # Task 4 adds the letter type
    assert all("." in k for k in KEYS)


def test_rules_model_is_route_neutral():
    assert set(EligibilityRules.model_fields) == {"grade", "language", "test", "grade_scales"}


def test_mount_checks_rules(tmp_path):
    from fastapi import FastAPI

    from app.os.api.mount import mount_os

    bad = _with(tmp_path, lambda e: e["language"][0].update(requirement="english_level"))
    env = {"OS_DATABASE_URL": "postgresql://unused/x", "OS_ENABLED": "true"}
    with pytest.raises(PlaybookError, match="english_level"):
        mount_os(FastAPI(), env=env, playbook_dir=bad.parent)
