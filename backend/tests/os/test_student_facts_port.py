"""P1-T4 Task 5: eligibility reads StudentFacts through a port (R-01, R-13). Synthetic values only. Postgres."""

import json
import re
import types as pytypes
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
import yaml

from app.os import ports
from app.os.adapters.counsellor import manifest
from app.os.adapters.standalone.student_facts import build as standalone_facts
from app.os.contracts.student_facts import FACT_KEY, StudentFactsV1
from app.os.documents.store import ProfileStore
from app.os.documents.types import DocumentType, DocumentTypeError, FieldSpec, TYPES_DIR, load_document_types
from app.os.eligibility.evaluate import evaluate
from app.os.eligibility.facts import profile_from_facts
from app.os.eligibility.notes import profile_of
from app.os.knowledge.port import Fact
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.ports import student_facts

pytestmark = [pytest.mark.req("R-01"), pytest.mark.req("R-13")]

APP_OS = Path(__file__).resolve().parents[2] / "app" / "os"
KEYS_YAML = Path(__file__).resolve().parents[2] / "app" / "pai_c" / "connect" / "student_facts_keys.yaml"
BOOKS = load_playbook_dir(PLAYBOOK_DIR) | load_playbook_dir(Path(__file__).parent / "playbooks")
TYPES = load_document_types()
TENANT = "pai"
NOW = datetime(2026, 11, 5, tzinfo=timezone.utc)


def facts_v1(student="stu-1", **by_key) -> StudentFactsV1:
    """`by_key`: fact key with dots as double underscores -> value, or (value, evidence)."""
    items = []
    for key, v in by_key.items():
        value, evidence = v if isinstance(v, tuple) else (v, "stated")
        items.append({"key": key.replace("__", "."), "value": None if evidence == "unknown" else value,
                      "evidence": evidence, "vault_version": 1})
    return StudentFactsV1.model_validate({"schema": "pai.student_facts.v1", "student_ref": student, "vault_version": 1,
                                          "built_at": NOW, "eligible_levels": None, "facts": items})


def fact(value, status="confirmed") -> Fact:
    return Fact(value=value, quote="q" if status == "confirmed" else "", url="https://uni.example/req",
                checked_at=datetime(2026, 10, 1, tzinfo=timezone.utc), intake_year=2027, status=status)


# A fake local entry test is not a document type; the test adds one of its own so the mapping covers it.
ENTRY = DocumentType(key="entry_test", version=1, label="Entry test",
                     fields=[FieldSpec(name="score", type="number", hint="Score", fact="test.entry_test.score")])
ALL_TYPES = TYPES | {"entry_test": ENTRY}

# (route, research facts, Vault facts, the equivalent document profile)
CASES = {
    "germany": ("germany_master", {"grade_requirement": fact({"german_max": 2.5}),
                                   "english_requirement": fact({"cefr": "B2", "ielts": 6.5}),
                                   "german_requirement": fact({"level": "none"}), "admission_test": fact(None)},
                {"education__bachelor__gpa": 3.2, "education__bachelor__gpa_scale": 4.0, "test__ielts__score": 7.0},
                {"transcript.cgpa": 3.2, "transcript.cgpa_scale": 4.0, "ielts_trf.overall": 7.0}),
    "ireland": ("ireland_master", {"grade_requirement": fact({"percent_min": 60}),
                                   "english_requirement": fact({"ielts": 6.5})},
                {"education__bachelor__percentage": 75, "test__ielts__score": 7.0},
                {"transcript.percentage": 75, "ielts_trf.overall": 7.0}),
    "pk_bs": ("pakistan_bs", {"merit_closing": fact({"aggregate": 80}), "entry_test_required": fact({"any_of": []})},
              {"education__intermediate__marks_obtained": 990, "education__intermediate__marks_total": 1100,
               "test__entry_test__score": 80},
              {"hssc_certificate.marks_obtained": 990, "hssc_certificate.marks_total": 1100, "entry_test.score": 80}),
    "pk_inter": ("pakistan_inter", {"merit_closing": fact({"aggregate": 80})},
                 {"education__matric__marks_obtained": 900, "education__matric__marks_total": 1100},
                 {"ssc_certificate.marks_obtained": 900, "ssc_certificate.marks_total": 1100}),
}


@pytest.mark.parametrize("route", sorted(CASES))
def test_vault_profile_evaluates_like_the_document_profile(route):
    book, research, vault, documents = CASES[route]
    profile = profile_from_facts(facts_v1(**vault), ALL_TYPES)
    assert profile == documents
    rules = BOOKS[(book, 1)].eligibility
    assert evaluate(rules, "p", research, profile) == evaluate(rules, "p", research, documents)


@pytest.mark.parametrize("evidence", ["stated", "shown", "confirmed"])
def test_known_evidence_levels_all_give_a_value(evidence):
    facts = facts_v1(test__ielts__score=(6.5, evidence))
    assert profile_from_facts(facts, TYPES) == {"ielts_trf.overall": 6.5}


def test_unknown_or_missing_fact_gives_no_value_and_needs_input():
    rules = BOOKS[("ireland_master", 1)].eligibility
    research = CASES["ireland"][1]
    facts = facts_v1(education__bachelor__percentage=(None, "unknown"), test__ielts__score=(7.0, "stated"))
    profile = profile_from_facts(facts, TYPES)
    assert profile == {"ielts_trf.overall": 7.0}  # an inferred fact is sent as unknown with no value
    card = evaluate(rules, "p", research, profile)
    grade = next(ln for ln in card.lines if ln.check == "grade")
    assert grade.status == "needs_input" and grade.have is None


def test_a_fact_key_the_types_do_not_map_is_ignored():
    assert profile_from_facts(facts_v1(budget__x=(1, "stated"), constraint__budget=("low", "stated")), TYPES) == {}


def test_profile_from_facts_is_pure():
    facts = facts_v1(test__ielts__score=6.5)
    assert profile_from_facts(facts, TYPES) == profile_from_facts(facts, TYPES)
    assert facts.facts[0].value == 6.5


# --- the startup check -----------------------------------------------------------------------------------------

def test_every_fact_key_in_the_types_matches_the_contract_pattern_and_the_key_map():
    keys = yaml.safe_load(KEYS_YAML.read_text(encoding="utf-8"))
    families, fields = keys["education"]["families"], set(keys["education"]["fields"])
    test_key = re.compile("^" + keys["tests"]["key"].replace("{type}", "[a-z0-9_]+").replace(".", r"\.") + "$")
    mapped = [(t.key, f.name, f.fact) for t in TYPES.values() for f in t.fields if f.fact]
    assert mapped, "the document types carry no fact: mapping"
    for doc, name, key in mapped:
        assert re.match(FACT_KEY, key), (doc, name, key)
        parts = key.split(".")
        in_education = parts[0] == "education" and parts[1] in families and ".".join(parts[2:]) in fields
        assert in_education or test_key.match(key), (doc, name, key)


def test_a_bad_fact_key_stops_startup(tmp_path):
    for path in TYPES_DIR.glob("*.yaml"):
        (tmp_path / path.name).write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    bad = tmp_path / "ssc_certificate.v1.yaml"
    bad.write_text(bad.read_text(encoding="utf-8").replace("education.matric.marks_total", "Education Matric"),
                   encoding="utf-8")
    with pytest.raises(DocumentTypeError, match="marks_total"):
        load_document_types(tmp_path)


# --- the port ----------------------------------------------------------------------------------------------------

@pytest.fixture
def mounted(engine, clean):
    ports.configure(pytypes.SimpleNamespace(engine=engine, settings=pytypes.SimpleNamespace(tenant_id=TENANT)))
    try:
        yield engine
    finally:
        ports.configure(None)


def own(engine, student="stu-1", **values):
    store = ProfileStore(engine, TENANT)
    for key, v in values.items():
        store.set(student, key.replace("__", "."), v, None, source="entered")


def counsellor(returns):
    calls = []

    def provider(student_ref):
        calls.append(student_ref)
        return returns

    return provider, calls


def test_standalone_adapter_builds_facts_from_os_profile_values(engine, clean):
    store = ProfileStore(engine, TENANT)
    store.set("stu-1", "transcript.cgpa", 3.2, None)
    store.set("stu-1", "ielts_trf.overall", 7.0, None, source="entered")
    store.set("stu-1", "min_passing_grade_letter.min_pass", "C", None)
    facts = standalone_facts(engine, TENANT, "stu-1", TYPES)
    by_key = {f.key: f for f in facts.facts}
    assert by_key["education.bachelor.gpa"].value == 3.2 and by_key["education.bachelor.gpa"].evidence == "confirmed"
    assert by_key["test.ielts.score"].evidence == "stated"
    assert by_key["min_passing_grade_letter.min_pass"].value == "C"  # no Vault key: carried under its own key
    assert profile_from_facts(facts, TYPES) == {"transcript.cgpa": 3.2, "ielts_trf.overall": 7.0}


def test_get_is_standalone_without_a_counsellor_adapter(mounted):
    own(mounted, transcript__cgpa=3.0)
    got = student_facts.get("stu-1")
    assert [f.key for f in got.facts] == ["education.bachelor.gpa"] and got.student_ref == "stu-1"


def test_get_uses_the_counsellor_adapter_only_while_the_module_is_on(mounted):
    provider, calls = counsellor(facts_v1(test__ielts__score=6.5).model_dump(by_alias=True))
    student_facts.configure(provider)
    own(mounted, transcript__cgpa=3.0)
    assert [f.key for f in student_facts.get("stu-1").facts] == ["education.bachelor.gpa"] and calls == []  # module off
    manifest.set_enabled(mounted, TENANT, True)
    assert [f.key for f in student_facts.get("stu-1").facts] == ["test.ielts.score"] and calls == ["stu-1"]


def test_get_falls_back_to_standalone_when_the_host_part_is_off(mounted):
    manifest.set_enabled(mounted, TENANT, True)
    student_facts.configure(counsellor(None)[0])  # the host answers None while its part is off
    own(mounted, transcript__cgpa=3.0)
    assert [f.key for f in student_facts.get("stu-1").facts] == ["education.bachelor.gpa"]


def test_configure_is_reset_by_ports_configure(mounted):
    student_facts.configure(counsellor(None)[0])
    ports.configure(None)
    assert student_facts.current() is None


def test_load_names_the_setting_and_never_a_value():
    for spec in ("", "nocolon", "no.such.module:thing", "os:nothing_here", "os:sep"):
        with pytest.raises(student_facts.StudentFactsSourceError, match="OS_STUDENT_FACTS"):
            student_facts.load(spec)
    assert student_facts.load("json:dumps") is json.dumps


# --- profile_of: flags off, the Vault, the interim overlay ---------------------------------------------------------

def plans_of(engine):
    return pytypes.SimpleNamespace(engine=engine, kernel=pytypes.SimpleNamespace(tenant_id=TENANT))


def today(engine, student="stu-1") -> dict:
    return {v["key"]: v["value"] for v in ProfileStore(engine, TENANT).all(student)}


def seed(engine):
    own(engine, transcript__cgpa=3.0, transcript__percentage=61.5, ielts_trf__overall=6.0,
        min_passing_grade_letter__min_pass="C", hssc_certificate__marks_obtained=700)


@pytest.mark.parametrize("setup", ["no_adapter", "adapter_none", "module_off"])
def test_flags_off_profile_is_exactly_todays_os_profile_values(mounted, setup):
    seed(mounted)
    provider, calls = counsellor(facts_v1(test__ielts__score=9.0).model_dump(by_alias=True))
    if setup == "adapter_none":
        student_facts.configure(counsellor(None)[0])
        manifest.set_enabled(mounted, TENANT, True)
    elif setup == "module_off":
        student_facts.configure(provider)
    got = profile_of(plans_of(mounted), "stu-1")
    assert json.dumps(got) == json.dumps(today(mounted)) and calls == []


def test_a_vault_value_wins_and_the_interim_overlay_fills_only_keys_the_vault_lacks(mounted):
    # interim: removed by T7 (the overlay of os_profile_values for keys the Vault lacks)
    seed(mounted)
    manifest.set_enabled(mounted, TENANT, True)
    vault = facts_v1(test__ielts__score=7.5, education__intermediate__marks_total=1100)
    student_facts.configure(counsellor(vault.model_dump(by_alias=True))[0])
    got = profile_of(plans_of(mounted), "stu-1")
    assert got["ielts_trf.overall"] == 7.5  # the Vault wins over the stored 6.0
    assert got["hssc_certificate.marks_total"] == 1100
    assert got["hssc_certificate.marks_obtained"] == 700  # the Vault lacks it: the overlay supplies it
    assert got["transcript.cgpa"] == 3.0 and got["min_passing_grade_letter.min_pass"] == "C"
    assert set(got) == set(today(mounted)) | {"hssc_certificate.marks_total"}


def test_an_unknown_vault_fact_does_not_hide_a_stored_value_but_gives_needs_input_without_one(mounted):
    # interim: removed by T7
    manifest.set_enabled(mounted, TENANT, True)
    vault = facts_v1(education__bachelor__percentage=(None, "unknown"), test__ielts__score=7.0)
    student_facts.configure(counsellor(vault.model_dump(by_alias=True))[0])
    profile = profile_of(plans_of(mounted), "stu-1")
    assert profile == {"ielts_trf.overall": 7.0}
    rules = BOOKS[("ireland_master", 1)].eligibility
    grade = next(ln for ln in evaluate(rules, "p", CASES["ireland"][1], profile).lines if ln.check == "grade")
    assert grade.status == "needs_input"
    own(mounted, transcript__percentage=70)
    assert profile_of(plans_of(mounted), "stu-1")["transcript.percentage"] == 70


# --- the red-flag search -----------------------------------------------------------------------------------------

NEW_FILES = ["eligibility/facts.py", "adapters/standalone/student_facts.py"]
FLAGGED = re.compile(r"pai_c|vault(?!_version)|counsellor|counselor|ielts|matric|hssc|\bssc|fsc\b|intermediate|bachelor|master|"
                     r"pakistan|german|ireland|\bgpa\b|education\.", re.IGNORECASE)


def test_red_flag_search_is_clean():
    hits = []
    for name in NEW_FILES:
        for n, line in enumerate((APP_OS / name).read_text(encoding="utf-8").splitlines(), 1):
            if FLAGGED.search(line):
                hits.append(f"{name}:{n}: {line.strip()}")
    assert hits == []
    for path in (APP_OS / "documents" / "types.py", APP_OS / "eligibility" / "notes.py"):
        assert "pai_c" not in path.read_text(encoding="utf-8")


def test_the_fact_keys_live_in_yaml_only():
    for path in APP_OS.rglob("*.py"):
        assert not re.search(r"""["']education\.""", path.read_text(encoding="utf-8")), path
