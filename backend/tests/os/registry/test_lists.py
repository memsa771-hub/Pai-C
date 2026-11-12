"""P2-T2: reading an official-list file (the H3 research shape) into registry rows (P2 spec §4.1, master R-35a).
The data here is fictional; real lists enter only through the import (P2 spec §5)."""

from datetime import UTC, date, datetime

import pytest
import yaml

from app.os.registry.lists import OfficialListError, load_official_lists, parse_official_lists

from .helpers import store

pytestmark = pytest.mark.req("R-32")

TEXT = """
region: Punjab
retrieved: 2026-11-07
lists:
  - id: alpha-recognised
    body: Alpha Regulator
    name: Recognised institutions
    url: https://lists.alpha.test/recognised
    institution_type: university_or_dai
    family: bachelor
    date: null
    row_count: 12
    count_quote: null
    count_method: counted list items
    read_method: curl + HTML markup count
    check2: correct
  - id: alpha-campuses
    body: Alpha Regulator
    name: Campuses
    url: https://lists.alpha.test/campuses
    institution_type: university_campus
    date: 2026-05-19
    row_count: null
    count_quote: "Total = 3+4=7"
    count_conflict_quote: "Total: 3"
    status: conflict
    check2: correct
    scope: only the northern jurisdiction
  - id: alpha-unreadable
    body: Alpha Board
    name: Participating colleges
    url: https://lists.alpha.test/colleges
    institution_type: college
    status: not_readable
    row_count: null
not_found:
  - what: something not found
domains:
  - body: Alpha Regulator
    domains: [alpha.test]
"""


def data() -> dict:
    return yaml.safe_load(TEXT)


def test_parse_lists():
    a, b, c = parse_official_lists(data(), country="PK")
    assert a.entity_id == "list:alpha-recognised" and a.kind == "official_list"
    assert a.region == "punjab"  # normalised from the spelling in the file (R-76)
    assert a.source_url == "https://lists.alpha.test/recognised"
    assert a.checked_at == datetime(2026, 11, 7, tzinfo=UTC)
    assert a.institution_type == "university_or_dai" and a.quote == ""
    assert a.attrs["row_count"] == 12 and a.attrs["body"] == "Alpha Regulator"
    assert a.attrs["count_confirmed"] is True and a.attrs["family"] == "bachelor"
    assert b.quote == "Total = 3+4=7" and b.attrs["row_count"] is None and b.attrs["status"] == "conflict"
    assert b.attrs["count_conflict_quote"] == "Total: 3" and b.attrs["date"] == date(2026, 5, 19).isoformat()
    assert b.attrs["extra"] == {"scope": "only the northern jurisdiction"}  # unknown keys are kept, not dropped
    assert c.attrs["status"] == "not_readable" and c.attrs["count_confirmed"] is False


def test_errors_name_the_list():
    d = data()
    d["region"] = "narnia"
    with pytest.raises(OfficialListError, match="region"):
        parse_official_lists(d, country="PK")
    d = data()
    del d["lists"][0]["url"]
    with pytest.raises(OfficialListError, match="alpha-recognised"):
        parse_official_lists(d, country="PK")
    d = data()
    d["lists"][1]["id"] = d["lists"][0]["id"]
    with pytest.raises(OfficialListError, match="twice"):
        parse_official_lists(d, country="PK")
    d = data()
    d["lists"][0]["row_count"] = "twelve"
    with pytest.raises(OfficialListError, match="row_count"):
        parse_official_lists(d, country="PK")
    with pytest.raises(OfficialListError):
        parse_official_lists({"lists": []}, country="PK")


def test_load_records_lists_and_is_repeatable(engine, clean, tmp_path):
    path = tmp_path / "alpha.yaml"
    path.write_text(TEXT, encoding="utf-8")
    s = store(engine)
    assert load_official_lists(s, path, country="PK", cause_ref="imp-1") == 3
    assert [p.list_id for p in s.list_progresses()] == ["list:alpha-recognised", "list:alpha-campuses",
                                                        "list:alpha-unreadable"]
    assert s.list_progress("list:alpha-recognised").published == 12
    assert load_official_lists(s, path, country="PK", cause_ref="imp-2") == 3
    assert [r.action for r in s.revisions("list:alpha-recognised")] == ["insert"]  # unchanged: no new revision


def test_count_is_confirmed_only_when_the_method_and_the_count_support_it():
    """I-4: a markup count, a count 'unconfirmed on import' or no count is never confirmed, whatever check2 says."""
    d = data()
    base = d["lists"][0]
    ok = {**base, "id": "ok"}
    markup = {**base, "id": "markup", "count_method": "markup_count of list items"}
    unconfirmed = {**base, "id": "unconf", "count_method": "counted list items (Unconfirmed on import)"}
    no_count = {**base, "id": "nocount", "row_count": None}
    d["lists"] = [ok, markup, unconfirmed, no_count]
    got = {e.entity_id: e.attrs["count_confirmed"] for e in parse_official_lists(d, country="PK")}
    assert got == {"list:ok": True, "list:markup": False, "list:unconf": False, "list:nocount": False}


def test_dates_may_be_text():
    d = data()
    d["retrieved"] = "2026-11-07"
    d["lists"][1]["date"] = "2026-05-19"
    a, b, _ = parse_official_lists(d, country="PK")
    assert a.checked_at == datetime(2026, 11, 7, tzinfo=UTC) and b.attrs["date"] == "2026-05-19"
    d["lists"][1]["date"] = "19 May"
    with pytest.raises(OfficialListError, match="alpha-campuses"):
        parse_official_lists(d, country="PK")
    d["lists"][1]["date"] = "2026-05-19"
    d["retrieved"] = "yesterday"
    with pytest.raises(OfficialListError, match="retrieved"):
        parse_official_lists(d, country="PK")
