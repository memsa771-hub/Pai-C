"""P2-T1: the region vocabulary, the fact classes and the one display rule (P2 spec P2-D7, §4.4; master R-25, R-26,
R-76, §8.2). Fictional values only."""

import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from app.os.knowledge import fact_classes as fc
from app.os.knowledge.display import display
from app.os.knowledge.port import Fact
from app.os.knowledge.profile import load_profile_dir
from app.os.knowledge.regions import UnknownRegion, countries, normalise_region, regions

APP_OS = Path(__file__).resolve().parents[2] / "app" / "os"
AT = datetime(2026, 11, 1, tzinfo=UTC)


@pytest.mark.req("R-76")
def test_master_r76_regions_all_present():
    names = {r.name for r in regions("PK")}
    assert names == {"Punjab", "Sindh", "Khyber Pakhtunkhwa", "Balochistan", "Islamabad Capital Territory",
                     "Azad Jammu and Kashmir", "Gilgit-Baltistan", "National", "Federal institution"}
    assert countries() == ["PK"]
    for r in regions("PK"):
        assert re.fullmatch(r"[a-z][a-z0-9_]*", r.code)


@pytest.mark.req("R-76")
@pytest.mark.parametrize("spelling,code", [
    ("Punjab", "punjab"), ("  punjab ", "punjab"), ("KPK", "khyber_pakhtunkhwa"), ("khyber-pakhtunkhwa", "khyber_pakhtunkhwa"),
    ("Azad Jammu & Kashmir", "azad_jammu_and_kashmir"), ("gilgit baltistan", "gilgit_baltistan"),
    ("federal-institution", "federal_institution"), ("national", "national"),
])
def test_normalise_accepted_spellings(spelling, code):
    assert normalise_region(spelling, "PK") == code


@pytest.mark.req("R-76")
@pytest.mark.parametrize("spelling", ["Punjabb", "North", "", "Northville"])
def test_normalise_rejects_others(spelling):
    with pytest.raises(UnknownRegion):
        normalise_region(spelling, "PK")


def test_unknown_country_rejected():
    with pytest.raises(UnknownRegion):
        regions("ZZ")


@pytest.mark.req("R-25")
def test_high_stakes_classes_of_master_8_2():
    cls = fc.classes()
    for key in ("deadline", "schedule_date", "merit_formula", "eligibility_threshold", "seat_category", "seat_quota",
                "fee", "test_date", "test_pattern", "test_syllabus", "unclassified"):
        assert cls[key].high_stakes, key
    assert not cls["document_list"].high_stakes
    assert fc.fact_class("never_heard_of") == "unclassified"
    assert fc.fact_class("deadline_close") == "deadline"
    assert fc.fact_class("deadline_close", "fee") == "fee"
    with pytest.raises(ValueError):
        fc.fact_class("x", "bogus")


@pytest.mark.req("R-25")
def test_every_field_in_use_has_a_class():
    used = set()
    for path in [*(APP_OS / "playbooks").glob("*.yaml"), *(Path(__file__).parent / "playbooks").glob("*.yaml")]:
        used |= set(re.findall(r"\bfact: *([a-z_]+)", path.read_text(encoding="utf-8")))
    for profile in load_profile_dir().values():
        used |= {f.name for f in profile.fields}
    for path in (APP_OS / "knowledge" / "seed").glob("germany_*.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        used |= set((data.get("route") or {}).keys())
        for prog in (data.get("programmes") or {}).values():
            used |= set(prog.keys())
    missing = sorted(f for f in used if fc.fact_class(f) == "unclassified")
    assert missing == []


def fact(status="confirmed", year=2027, term="", **kw) -> Fact:
    return Fact(value="x", quote="q", url="https://site.test/a", checked_at=AT, intake_year=year, status=status,
                intake_term=term, **kw)


@pytest.mark.req("R-25")
@pytest.mark.parametrize("field,status,level,shown", [
    ("deadline_close", "verified", "verified", True),
    ("deadline_close", "confirmed", "not_confirmed", False),
    ("deadline_close", "unconfirmed", "not_confirmed", False),
    ("deadline_close", "stale", "not_confirmed", False),
    ("required_documents", "verified", "verified", True),
    ("required_documents", "confirmed", "confirmed", True),
    ("required_documents", "unconfirmed", "not_confirmed", False),
    ("required_documents", "stale", "not_confirmed", False),
    ("unknown_field", "confirmed", "not_confirmed", False),
])
def test_display_matrix(field, status, level, shown):
    d = display(fact(status), field, intake_year=2027)
    assert (d.level, d.show_value, d.other_intake, d.year_label) == (level, shown, False, None)


def test_display_missing_and_estimate():
    assert display(None, "deadline_close", intake_year=2027).level == "missing"
    assert not display(None, "deadline_close", intake_year=2027).show_value
    e = display(None, "deadline_close", intake_year=2027, estimate=True)
    assert (e.level, e.show_value) == ("estimated", True)


@pytest.mark.req("R-26")
def test_other_intake_always_labelled():
    d = display(fact("verified", year=2026), "deadline_close", intake_year=2027)
    assert (d.level, d.other_intake, d.year_label) == ("verified", True, 2026)
    t = display(fact("verified", term="spring"), "deadline_close", intake_year=2027, intake_term="fall")
    assert (t.other_intake, t.year_label) == (True, 2027)
    same = display(fact("verified", term=""), "deadline_close", intake_year=2027, intake_term="fall")
    assert not same.other_intake  # a term not recorded is not another intake


def test_explicit_class_wins():
    assert display(fact("confirmed", fact_class="document_list"), "deadline_close", intake_year=2027).show_value
