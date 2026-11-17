"""P2-T2: what a registry entry must carry (P2 spec §4.1, R-60 "stored once with its official-list source", R-76)."""

from datetime import UTC, datetime

import pytest

from app.os.registry.model import KIND_PREFIX, RegistryEntry, slug

pytestmark = pytest.mark.req("R-32")
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)


def entry(**kw) -> RegistryEntry:
    base = dict(entity_id="inst:alpha-test-university", kind="institution", name="Alpha Test University",
                region="punjab", list_ids=("list:alpha-list",), source_url="https://lists.alpha.test/universities",
                quote="Alpha Test University, Lahore", checked_at=AT)
    return RegistryEntry(**{**base, **kw})


def test_valid_entry_and_defaults():
    e = entry()
    assert e.status == "active" and e.aliases == () and e.attrs == {}


def test_every_kind_has_a_prefix_and_the_id_must_use_it():
    assert set(KIND_PREFIX) == {"regulator", "board", "admission_body", "admission_system", "entry_test",
                                "institution", "campus", "seat_category", "calendar", "official_list"}
    with pytest.raises(ValueError, match="prefix"):
        entry(entity_id="campus:alpha")
    with pytest.raises(ValueError, match="id"):
        entry(entity_id="inst:Alpha Test")


def test_slug():
    assert slug("Alpha  Test University (Main)") == "alpha-test-university-main"
    with pytest.raises(ValueError):
        slug("!!!")


def test_source_is_required():
    with pytest.raises(ValueError, match="source"):
        entry(source_url="")
    with pytest.raises(ValueError, match="https"):
        entry(source_url="http://lists.alpha.test/x")
    with pytest.raises(ValueError, match="quote"):
        entry(quote=" ")
    with pytest.raises(ValueError, match="timezone"):
        entry(checked_at=datetime(2026, 11, 1))


def test_official_list_needs_no_quote():
    e = entry(entity_id="list:alpha-list", kind="official_list", list_ids=(), quote="", region="national")
    assert e.quote == ""


def test_institution_and_campus_name_their_lists():
    with pytest.raises(ValueError, match="official list"):
        entry(list_ids=())
    with pytest.raises(ValueError, match="official list"):
        entry(entity_id="campus:alpha-north", kind="campus", list_ids=(), parent_id="inst:alpha-test-university")


def test_region_is_in_the_vocabulary():
    with pytest.raises(ValueError, match="region"):
        entry(region="narnia")
    with pytest.raises(ValueError, match="region"):
        entry(region=None)
    assert entry(entity_id="cat:open-merit", kind="seat_category", list_ids=(), region=None,
                 parent_id="sys:x").region is None


def test_campus_needs_a_parent():
    with pytest.raises(ValueError, match="parent"):
        entry(entity_id="campus:alpha-north", kind="campus")


def test_status_and_successor():
    with pytest.raises(ValueError, match="status"):
        entry(status="gone")
    with pytest.raises(ValueError, match="successor"):
        entry(status="merged")
    assert entry(status="merged", successor_id="inst:beta").successor_id == "inst:beta"
    with pytest.raises(ValueError, match="successor"):
        entry(successor_id="inst:beta")  # an active entity has no successor


def test_domains_are_bare():
    with pytest.raises(ValueError, match="domain"):
        entry(official_domains=("https://alpha.test",))
    assert entry(official_domains=("alpha.test", "www.alpha.test")).official_domains == ("alpha.test", "www.alpha.test")
