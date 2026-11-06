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


def vault_on(engine, **by_key):
    manifest.set_enabled(engine, TENANT, True)
    student_facts.configure(counsellor(facts_v1(**by_key).model_dump(by_alias=True))[0])


def grade_of(profile, route="germany"):
    book, research = CASES[route][0], CASES[route][1]
    card = evaluate(BOOKS[(book, 1)].eligibility, "p", research, profile)
    return next(ln for ln in card.lines if ln.check == "grade")


def test_a_vault_value_wins_and_the_interim_overlay_fills_only_types_the_vault_lacks(mounted):
    # interim: removed by T7 (the overlay of os_profile_values for document types the Vault does not hold)
    seed(mounted)
    vault_on(mounted, test__ielts__score=7.5, education__intermediate__marks_total=1100)
    got = profile_of(plans_of(mounted), "stu-1")
    assert got["ielts_trf.overall"] == 7.5  # the Vault wins over the stored 6.0
    assert got["hssc_certificate.marks_total"] == 1100
    assert "hssc_certificate.marks_obtained" not in got  # the Vault holds this type: nothing of it from the overlay
    assert got["transcript.cgpa"] == 3.0 and got["min_passing_grade_letter.min_pass"] == "C"  # types the Vault lacks
    assert set(got) == {"ielts_trf.overall", "hssc_certificate.marks_total", "transcript.cgpa",
                        "transcript.percentage", "min_passing_grade_letter.min_pass"}


def test_vault_cgpa_without_a_scale_never_mixes_with_an_os_document(mounted):
    # interim: removed by T7
    own(mounted, transcript__cgpa=3.9, transcript__cgpa_scale=5.0, transcript__percentage=40)
    vault_on(mounted, education__bachelor__gpa=3.2)
    got = profile_of(plans_of(mounted), "stu-1")
    assert got == {"transcript.cgpa": 3.2}  # neither the OS scale (5.0) nor the OS percentage is mixed in
    # the evaluator reads a CGPA with no scale on the route's own scale; mixed with the OS scale it would be "other_scale"
    mixed = {"transcript.cgpa": 3.2, "transcript.cgpa_scale": 5.0, "transcript.percentage": 40}
    assert grade_of(got).status == "likely_meets" and grade_of(mixed).status == "likely_below"


def test_an_unknown_vault_fact_stays_needs_input_over_an_os_document(mounted):
    # interim: removed by T7
    own(mounted, hssc_certificate__marks_obtained=990, hssc_certificate__marks_total=1100, entry_test__score=80)
    vault_on(mounted, education__intermediate__marks_obtained=(None, "unknown"))
    got = profile_of(plans_of(mounted), "stu-1")
    assert not any(k.startswith("hssc_certificate.") for k in got) and got["entry_test.score"] == 80
    assert grade_of(got, "pk_bs").status == "needs_input"


def test_a_type_the_vault_does_not_hold_still_comes_from_the_overlay(mounted):
    # interim: removed by T7
    own(mounted, min_passing_grade_letter__min_pass="C", entry_test__score=80)
    vault_on(mounted, test__ielts__score=7.0)
    assert profile_of(plans_of(mounted), "stu-1") == {"min_passing_grade_letter.min_pass": "C", "entry_test.score": 80,
                                                      "ielts_trf.overall": 7.0}


def test_an_answer_for_another_student_is_ignored(mounted, caplog):
    own(mounted, transcript__cgpa=3.0)
    manifest.set_enabled(mounted, TENANT, True)
    student_facts.configure(counsellor(facts_v1(student="stu-2", test__ielts__score=9.0).model_dump(by_alias=True))[0])
    with caplog.at_level("ERROR"):
        got = student_facts.get("stu-1")
        assert profile_of(plans_of(mounted), "stu-1") == {"transcript.cgpa": 3.0}
    assert [f.key for f in got.facts] == ["education.bachelor.gpa"]
    assert "student_ref_mismatch" in caplog.text and "stu-2" not in caplog.text


def test_an_adapter_answering_none_skips_the_standalone_round_trip(mounted, monkeypatch):
    own(mounted, transcript__cgpa=3.0)
    manifest.set_enabled(mounted, TENANT, True)
    student_facts.configure(counsellor(None)[0])

    def boom(*a, **k):
        raise AssertionError("standalone facts built")

    monkeypatch.setattr(student_facts, "standalone_build", boom)
    assert profile_of(plans_of(mounted), "stu-1") == {"transcript.cgpa": 3.0}


def test_profile_uses_the_document_types_the_process_loaded(mounted, tmp_path):
    from app.os.eligibility import facts as eligibility_facts

    for path in TYPES_DIR.glob("*.yaml"):
        text = path.read_text(encoding="utf-8")
        if path.name.startswith("ielts_trf"):
            text = text.replace("test.ielts.score", "test.other.score")
        (tmp_path / path.name).write_text(text, encoding="utf-8")
    try:
        eligibility_facts.configure_types(load_document_types(tmp_path))
        vault_on(mounted, test__other__score=6.5, test__ielts__score=9.0)
        assert profile_of(plans_of(mounted), "stu-1") == {"ielts_trf.overall": 6.5}
    finally:
        eligibility_facts.configure_types(None)


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


# --- P1-T7 Task 4: with ONE_UPLOAD on too, the interim overlay is replaced by the per-field rule (D-y12) ---------------


@pytest.fixture
def one_upload_on():
    from app.os.ports import document_files

    document_files.configure(enabled=lambda: True)
    yield
    document_files.configure()


def test_both_on_a_vault_value_wins_and_only_fields_without_a_vault_key_come_from_the_stored_values(mounted, one_upload_on):
    seed(mounted)
    vault_on(mounted, test__ielts__score=7.5, education__intermediate__marks_total=1100)
    got = profile_of(plans_of(mounted), "stu-1")
    assert got["ielts_trf.overall"] == 7.5 and got["hssc_certificate.marks_total"] == 1100
    assert "hssc_certificate.marks_obtained" not in got
    assert "transcript.cgpa" not in got and "transcript.percentage" not in got  # a `fact:` field is the Vault's alone
    assert got["min_passing_grade_letter.min_pass"] == "C"  # no Vault type: still the stored value
    assert set(got) == {"ielts_trf.overall", "hssc_certificate.marks_total", "min_passing_grade_letter.min_pass"}


def test_both_on_vault_cgpa_without_a_scale_never_mixes_with_an_os_document(mounted, one_upload_on):
    own(mounted, transcript__cgpa=3.9, transcript__cgpa_scale=5.0, transcript__percentage=40)
    vault_on(mounted, education__bachelor__gpa=3.2)
    assert profile_of(plans_of(mounted), "stu-1") == {"transcript.cgpa": 3.2}


def test_both_on_an_unknown_vault_fact_stays_needs_input_over_an_os_document(mounted, one_upload_on):
    own(mounted, hssc_certificate__marks_obtained=990, hssc_certificate__marks_total=1100, entry_test__score=80)
    vault_on(mounted, education__intermediate__marks_obtained=(None, "unknown"))
    got = profile_of(plans_of(mounted), "stu-1")
    assert not any(k.startswith("hssc_certificate.") for k in got) and got["entry_test.score"] == 80
    assert grade_of(got, "pk_bs").status == "needs_input"


def test_both_on_a_field_without_a_vault_key_still_comes_from_the_stored_values(mounted, one_upload_on):
    own(mounted, min_passing_grade_letter__min_pass="C", entry_test__score=80)
    vault_on(mounted, test__ielts__score=7.0)
    assert profile_of(plans_of(mounted), "stu-1") == {"min_passing_grade_letter.min_pass": "C", "entry_test.score": 80,
                                                      "ielts_trf.overall": 7.0}


FLAG = {"on": True}


def flag_on() -> bool:
    return FLAG["on"]


@pytest.mark.req("R-01")
def test_the_worker_is_given_the_one_upload_gate_and_profile_of_follows_the_per_field_rule(mounted, os_db, monkeypatch):
    """P1-T7 final review I1: the worker loads OS_DOCUMENTS_ENABLED, so its eligibility uses the same rule as the API."""
    from dbos import DBOS

    from app.os.ports import document_files
    from app.os.runner import worker
    from app.os.settings import load_settings

    monkeypatch.setattr(worker, "register_job", lambda *a: None)
    for var in ("OS_TEST_RESEARCH_MODEL", "OS_TEST_DOCUMENT_MODEL", "OS_TEST_STATEMENT_MODEL", "OS_TEST_REPLAN_MODEL",
                "OS_EXTRA_MODULES"):
        monkeypatch.delenv(var, raising=False)
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true", "OS_WORKER_ID": "w1",
                              "OS_DOCUMENTS_ENABLED": f"{__name__}:flag_on"})
    seed(mounted)
    try:
        _, _, client, _ = worker.build(settings)  # builds what the worker runs; sets the port
        client.destroy()
        vault_on(mounted, test__ielts__score=7.5, education__intermediate__marks_total=1100)  # after: build resets it
        FLAG["on"] = True
        got = profile_of(plans_of(mounted), "stu-1")
        assert document_files.enabled() is True
        assert "transcript.cgpa" not in got  # per-field rule: a field with a Vault key is the Vault's alone
        assert got["ielts_trf.overall"] == 7.5 and got["min_passing_grade_letter.min_pass"] == "C"
        FLAG["on"] = False  # the flag off: T4's overlay again
        assert profile_of(plans_of(mounted), "stu-1")["transcript.cgpa"] == 3.0
        manifest.set_enabled(mounted, TENANT, False)  # the OS's own module row also gates it
        FLAG["on"] = True
        assert document_files.enabled() is False
    finally:
        FLAG["on"] = True
        document_files.configure()
        DBOS.destroy(destroy_registry=True)
