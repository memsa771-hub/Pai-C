"""Freeze exception 3 (P2-D28, P2 spec §4.11): the academic calendar and admission rules through Knowledge.

Proof asked by the spec: the roadmap time estimate is identical with the flag off and on, apart from the values the
import verified. Fictional facts only (registry ref `cal:alpha-...`); the Knowledge read is the bridge, stubbed here.
"""

from datetime import date

import pytest

from app import pai_os_bridge
from app.config import config
from app.pai_c.connect import policy_knowledge as pk
from app.pai_c.paths.fields import study_fields
from app.pai_c.roadmap import calendar as cal
from app.pai_c.roadmap import rules
from app.pai_c.roadmap.timeline import estimate
from tests.test_roadmap_steps import fsc, route

REAL_READ = pai_os_bridge.confirmed_knowledge

pytestmark = [pytest.mark.req("R-44"), pytest.mark.req("R-20")]

RESULT_LINK = {"target": "event", "key": "hssc_part2_result", "attr": "months",
               "fact": {"scope": "registry", "ref": "cal:alpha-result", "field": "result_date"}}


def _fact(value, url="https://alpha.example/notice"):
    return {"value": value, "url": url, "status": "confirmed", "intake_year": 2027}


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    pk.clear()
    yield
    pk.clear()


def _links(monkeypatch, calendar=(), admission_rules=()):
    monkeypatch.setattr(pk, "links", lambda: {"calendar": list(calendar), "admission_rules": list(admission_rules)})


def _part(monkeypatch, on: bool, module: bool = True):
    monkeypatch.setattr(config, pk.PART, on)
    monkeypatch.setattr(pai_os_bridge, "counsellor_module_on", lambda: module)


def _grid(today=date(2026, 10, 29)):
    records = [fsc("pre_engineering", status="current"), fsc("pre_medical", 70), fsc("pre_engineering", 50),
               {"qualification_name": "matric", "academic_status": "current"}]
    out = {}
    for field in sorted(study_fields()):
        for i, record in enumerate(records):
            out[(field, i)] = estimate(route(field, record), field, today)
    return out


def test_shipped_links_are_empty_and_well_formed():
    """No link is guessed: the file ships empty until rows are imported."""
    pk.links.cache_clear()
    assert pk.links() == {"calendar": [], "admission_rules": []}


def test_off_returns_the_file_itself(monkeypatch):
    _part(monkeypatch, False)
    called = []
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge", lambda *a: called.append(a) or {})
    assert cal.calendar() is cal._file()
    assert rules._data() is rules._file()
    assert not called


def test_on_with_no_links_is_identical(monkeypatch):
    """Replay: every study field x four students, flag off and on (no links): the same estimate."""
    _part(monkeypatch, False)
    off = _grid()
    _part(monkeypatch, True)
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge", lambda *a: pytest.fail("no links: no read"))
    assert _grid() == off


def test_only_the_verified_value_changes(monkeypatch):
    """A confirmed result date replaces that event's months and leads its sources; every estimate that does not use the
    event is unchanged, and those that do differ only through it."""
    _part(monkeypatch, False)
    off = _grid()
    _part(monkeypatch, True)
    _links(monkeypatch, calendar=[RESULT_LINK])
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge",
                        lambda keys, year: {tuple(k): _fact({"date": "2027-08-14", "tz": "UTC"}) for k in keys})
    row = cal.event("hssc_part2_result")
    assert row["months"] == [8] and row["sources"][0] == "https://alpha.example/notice"
    assert row["confidence"] == "official"
    on = _grid()
    changed = [k for k in off if on[k] != off[k]]
    assert changed  # the current FSc students wait for this result
    for key in changed:
        assert any(b["event_key"] == "hssc_part2_result" for b in off[key]["basis"])
        assert [b for b in on[key]["basis"] if b["event_key"] == "hssc_part2_result"][0]["month"] == 8
    untouched = [k for k in off if not any(b["event_key"] == "hssc_part2_result" for b in off[k]["basis"])]
    assert untouched and all(on[k] == off[k] for k in untouched)


@pytest.mark.parametrize("facts", [
    {},  # no confirmed fact (unconfirmed and stale are not returned by the read)
    {("registry", "cal:alpha-result", "result_date"): _fact({"value": "August", "unit": "text"})},  # not a date
])
def test_no_confirmed_date_keeps_the_file(monkeypatch, facts):
    _part(monkeypatch, True)
    _links(monkeypatch, calendar=[RESULT_LINK])
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge", lambda keys, year: facts)
    file_row = next(r for r in cal._file()["events"] if r["key"] == "hssc_part2_result")
    assert cal.event("hssc_part2_result")["months"] == file_row["months"]
    assert cal.calendar()["events"] == cal._file()["events"]


def test_module_off_or_os_failure_keeps_the_file(monkeypatch):
    _part(monkeypatch, True, module=False)
    _links(monkeypatch, calendar=[RESULT_LINK])
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge", lambda *a: pytest.fail("module off: no read"))
    assert cal.calendar() is cal._file()
    pk.clear()
    _part(monkeypatch, True)
    _links(monkeypatch, calendar=[RESULT_LINK])
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge", REAL_READ)  # OS not mounted here: the read gives {}
    assert pai_os_bridge.confirmed_knowledge([("registry", "x", "y")], 2027) == {}
    assert cal.calendar()["events"] == cal._file()["events"]


def test_a_result_that_fails_the_checks_keeps_the_file(monkeypatch):
    file_data = cal._file()
    _part(monkeypatch, True)
    _links(monkeypatch, calendar=[RESULT_LINK])
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge",
                        lambda keys, year: {tuple(k): _fact({"date": "2027-08-14"}) for k in keys})

    def refuse(data):
        raise cal.CalendarError("broken")

    monkeypatch.setattr(cal, "validate", refuse)
    assert cal.calendar() is file_data


def test_rule_min_percent_from_a_confirmed_fact(monkeypatch):
    target = next(r for r in rules._file()["rules"] if r["min_percent"] is not None)
    field = (target["applies_to"].get("fields") or [None])[0]
    assert field
    link = {"applies_to": target["applies_to"], "attr": "min_percent",
            "fact": {"scope": "programme", "ref": "prog:alpha", "field": "min_percent"}}
    _part(monkeypatch, True)
    _links(monkeypatch, admission_rules=[link])
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge",
                        lambda keys, year: {tuple(k): _fact({"value": 65, "unit": "percent"}) for k in keys})
    rule = rules.rule_for(field)
    assert rule.min_percent == 65 and rule.sources[0] == "https://alpha.example/notice"
    assert rule.confidence == target["confidence"]  # other values in the rule are still the file's
    assert rules._file()["rules"][rules._file()["rules"].index(target)]["min_percent"] == target["min_percent"]
    monkeypatch.setattr(config, pk.PART, False)
    assert rules.rule_for(field).min_percent == target["min_percent"]


def test_text_value_never_becomes_a_rule(monkeypatch):
    target = next(r for r in rules._file()["rules"] if r["min_percent"] is not None)
    link = {"applies_to": target["applies_to"], "attr": "min_percent",
            "fact": {"scope": "programme", "ref": "prog:alpha", "field": "min_percent"}}
    _part(monkeypatch, True)
    _links(monkeypatch, admission_rules=[link])
    monkeypatch.setattr(pai_os_bridge, "confirmed_knowledge",
                        lambda keys, year: {tuple(k): _fact({"value": "about 65", "unit": "text"}) for k in keys})
    assert rules._data()["rules"] == rules._file()["rules"]
