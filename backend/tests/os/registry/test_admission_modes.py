"""P3-T3 (ADR-001 D3; master R-38): admission modes are a data vocabulary, and the steps a mode fact decides stay
provisional until that fact is `verified`. Synthetic data only: no system, region or mode of any real place."""

import copy
from pathlib import Path

import pytest
import yaml

from app.os.compiler import compile_plan
from app.os.knowledge.fact_classes import deciding_level, fact_class, is_high_stakes
from app.os.playbooks import Playbook
from app.os.registry.admission_modes import (
    MODES_FILE,
    AdmissionModeError,
    admission_modes,
    check_mode_fact,
    parse,
    vocabulary,
)
from tests.os.test_compiler import IE, TODAY, contract, deadlines, fact, task

pytestmark = pytest.mark.req("R-38")


def raw() -> dict:
    return yaml.safe_load(MODES_FILE.read_text(encoding="utf-8"))


# --- the vocabulary ---------------------------------------------------------------------------------------------------

def test_the_vocabulary_loads_the_three_generic_modes():
    modes = admission_modes()
    assert set(modes) == {"central_ranked", "central_portal", "per_institution"}
    for m in modes.values():
        assert m.label and m.description
        assert m.calendars and all(m.calendars.values())
        assert "admits" in m.links
    assert modes["per_institution"].calendar_of == "institution"
    assert modes["central_ranked"].calendar_of == "admission_system"
    v = vocabulary()
    assert (v.field, v.entity_kind, v.requires) == ("admission_mode", "admission_system", "verified")


def test_the_mode_field_is_an_application_route_fact_that_decides_only_when_verified():
    assert fact_class("admission_mode") == "application_route"
    assert not is_high_stakes("application_route")  # Q9 default: no own high-stakes class; D3 gates the steps instead
    assert deciding_level("admission_mode") == "verified"
    assert deciding_level("application_route") == "confirmed"  # every other field decides as before


def test_the_vocabulary_names_no_place():
    text = MODES_FILE.read_text(encoding="utf-8").lower()
    from app.os.knowledge import regions

    names = {r.name.lower() for c in regions.countries() for r in regions.regions(c) if r.code != "national"}
    assert names and not [n for n in names if n in text]


@pytest.mark.parametrize("change, message", [
    (lambda d: d["modes"]["central_portal"]["calendars"].update(admission=["weather_day"]), "not dates of a admission"),
    (lambda d: d["modes"]["central_portal"]["calendars"].update(harvest=["application_open"]), "unknown calendar type"),
    (lambda d: d["modes"]["central_portal"].update(links=["admits", "befriends"]), "unknown link rels"),
    (lambda d: d["modes"]["central_portal"].update(calendar_of="campus"), "cannot hold a calendar"),
    (lambda d: d["modes"]["central_portal"].update(description=" "), "needs a description"),
    (lambda d: d["modes"]["central_portal"].update(colour="red"), "unknown keys"),
    (lambda d: d["modes"].update({"Bad Mode": d["modes"]["central_portal"]}), "snake case"),
    (lambda d: d.update(entity_kind="planet"), "not a registry kind"),
    (lambda d: d.update(field="mode_of_travel"), "not listed in fact_classes"),
    (lambda d: d.update(requires="confirmed"), "decides_at"),
    (lambda d: d.update(modes={}), "at least one mode"),
])
def test_a_bad_entry_is_refused(change, message):
    data = copy.deepcopy(raw())
    change(data)
    with pytest.raises(AdmissionModeError, match=message):
        parse(data)


# --- the import rule --------------------------------------------------------------------------------------------------

def test_the_mode_rule_accepts_a_mode_on_a_system_only():
    assert check_mode_fact("admission_mode", "central_portal", "admission_system") is None
    assert check_mode_fact("deadline_close", "anything", "institution") is None  # other fields are not its business
    reason, detail = check_mode_fact("admission_mode", "lottery", "admission_system")
    assert reason == "unknown_admission_mode" and "central_ranked" in detail
    reason, detail = check_mode_fact("admission_mode", "central_portal", "institution")
    assert reason == "mode_on_wrong_kind" and "admission_system" in detail and "institution" in detail
    assert check_mode_fact("admission_mode", "central_portal", None)[0] == "mode_on_wrong_kind"


# --- provisional until verified (D3), on a programme-level condition: the system path is P3-T4 --------------------------

def gated_book() -> Playbook:
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][0]["condition"] = {"fact": "admission_mode", "in": ["central_portal"]}
    return Playbook.model_validate(data)


def mode(value, status):
    f = fact(value, "confirmed" if status == "verified" else status)
    if status == "verified":
        from dataclasses import replace

        f = replace(f, status="verified")
    return f


@pytest.mark.parametrize("status, provisional", [("unconfirmed", True), ("confirmed", True), ("verified", False)])
def test_a_mode_gated_step_is_firm_only_when_the_mode_is_verified(status, provisional):
    facts = {**deadlines(p1="2027-07-15"), ("p1", "admission_mode"): mode("central_portal", status)}
    d = compile_plan(contract(["p1"]), gated_book(), {}, facts, TODAY)
    assert task(d, "apply@p1").provisional is provisional
    keys = {t.instance_key for t in d.tasks}
    assert ("confirm_fact@p1:admission_mode" in keys) is provisional


def test_a_confirmed_mode_that_rules_a_step_out_keeps_the_decision_checkable():
    facts = {**deadlines(p1="2027-07-15"), ("p1", "admission_mode"): mode("per_institution", "confirmed")}
    keys = {t.instance_key for t in compile_plan(contract(["p1"]), gated_book(), {}, facts, TODAY).tasks}
    assert "apply@p1" not in keys and "confirm_fact@p1:admission_mode" in keys
    facts[("p1", "admission_mode")] = mode("per_institution", "verified")
    keys = {t.instance_key for t in compile_plan(contract(["p1"]), gated_book(), {}, facts, TODAY).tasks}
    assert "apply@p1" not in keys and "confirm_fact@p1:admission_mode" not in keys


def test_another_field_still_decides_from_confirmed():
    data = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    data["tasks"][0]["condition"] = {"fact": "application_route", "in": ["direct"]}
    facts = {**deadlines(p1="2027-07-15"), ("p1", "application_route"): fact("direct", "confirmed")}
    d = compile_plan(contract(["p1"]), Playbook.model_validate(data), {}, facts, TODAY)
    assert not task(d, "apply@p1").provisional


def test_the_rule_is_read_from_data_not_from_the_field_name(tmp_path, monkeypatch):
    """Raise another field in `decides_at` and it behaves the same: the compiler names no field."""
    from app.os.knowledge import fact_classes as fc

    data = yaml.safe_load(fc.CLASSES_FILE.read_text(encoding="utf-8"))
    data["decides_at"]["application_route"] = "verified"
    path = Path(tmp_path) / "fact_classes.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    loaded = fc._load.__wrapped__(path)
    monkeypatch.setattr(fc, "_load", lambda: loaded)
    book = IE.model_dump(mode="json", by_alias=True, exclude_none=True)
    book["tasks"][0]["condition"] = {"fact": "application_route", "in": ["direct"]}
    facts = {**deadlines(p1="2027-07-15"), ("p1", "application_route"): fact("direct", "confirmed")}
    d = compile_plan(contract(["p1"]), Playbook.model_validate(book), {}, facts, TODAY)
    assert task(d, "apply@p1").provisional


def test_decides_at_refuses_an_unknown_level(tmp_path):
    from app.os.knowledge import fact_classes as fc

    data = yaml.safe_load(fc.CLASSES_FILE.read_text(encoding="utf-8"))
    data["decides_at"]["admission_mode"] = "sure"
    path = Path(tmp_path) / "fact_classes.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="unknown levels"):
        fc._load.__wrapped__(path)
