"""P1-T3 Task 2: data behind the choice screen: country names to ISO, the routes a student can pick, intake terms and
the places for a route (R-79, D-f, D-g). The OS bridge and the Vault readers are stubbed; fictional data."""

from datetime import date
from unittest.mock import patch

import pytest

from app.pai_c.connect import places

pytestmark = pytest.mark.req("R-79")

ROUTES = [
    {"key": "home_bs", "origin": "PK", "destination": "PK", "level": "bachelor", "intake_terms": ["autumn"]},
    {"key": "de_master", "origin": "PK", "destination": "DE", "level": "master", "intake_terms": ["winter"]},
    {"key": "ie_bachelor", "origin": "PK", "destination": "IE", "level": "bachelor", "intake_terms": []},
    {"key": "other_origin", "origin": "IN", "destination": "FR", "level": "bachelor", "intake_terms": ["fall"]},
]
TODAY = date(2026, 11, 5)


def vault(country="Pakistan", targets=("Ireland",)):
    values = {"location.current_country": country, "preferences.target_countries": list(targets) or None}
    return lambda db, ws, key: values.get(key)


@pytest.fixture
def stubs():
    with patch("app.pai_os_bridge.list_routes", return_value=ROUTES), \
         patch.object(places, "_standing_level", return_value="matric"), \
         patch.object(places, "_vault_value", vault()), \
         patch.object(places, "_eligible_levels", return_value=None):
        yield


def test_to_iso_maps_names():
    assert places.to_iso("Pakistan") == "PK"
    assert places.to_iso(" germany ") == "DE"
    assert places.to_iso("UNITED  kingdom") == "GB"
    assert places.to_iso("Atlantis") is None
    assert places.to_iso("") is None
    assert places.to_iso(None) is None


def test_next_level_from_study_fields():
    assert places.next_level("matric", "electrical_engineering") == "bachelor"
    assert places.next_level(None, None) == "bachelor"
    assert places.next_level("bachelor", "electrical_engineering") == "master"
    assert places.next_level("bachelor", "no_such_field") == "bachelor"


def test_choice_options_before_intermediate(stubs):
    got = places.choice_options(None, "w1", "electrical_engineering", today=TODAY)
    assert got["origin"] == "PK" and got["level"] == "bachelor"
    by = {d["code"]: d for d in got["destinations"]}
    assert set(by) == {"PK", "IE"}  # home plus the routes at that level from this origin
    assert by["PK"] == {"code": "PK", "supported": True, "route_key": "home_bs"}
    assert by["IE"] == {"code": "IE", "supported": True, "route_key": "ie_bachelor"}
    assert got["preselected_destination"] == "IE"
    assert got["years"] == [2026, 2027, 2028, 2029]
    assert got["intake_terms"]["PK"] == ["autumn"]
    assert got["intake_terms"]["IE"] == places.generic_terms()  # a route without terms falls back to generic


def test_unknown_origin_offers_every_route_destination_at_the_level():
    with patch("app.pai_os_bridge.list_routes", return_value=ROUTES), \
         patch.object(places, "_standing_level", return_value="matric"), \
         patch.object(places, "_eligible_levels", return_value=None), \
         patch.object(places, "_vault_value", vault(country="Atlantis", targets=())):
        got = places.choice_options(None, "w1", None, today=TODAY)
    assert got["origin"] is None
    assert {d["code"] for d in got["destinations"]} == {"PK", "IE", "FR"}
    assert got["preselected_destination"] is None


def test_target_outside_the_routes_is_offered_as_unsupported():
    with patch("app.pai_os_bridge.list_routes", return_value=ROUTES), \
         patch.object(places, "_standing_level", return_value="matric"), \
         patch.object(places, "_eligible_levels", return_value=None), \
         patch.object(places, "_vault_value", vault(targets=("Canada",))):
        got = places.choice_options(None, "w1", None, today=TODAY)
    by = {d["code"]: d for d in got["destinations"]}
    assert by["CA"] == {"code": "CA", "supported": False, "route_key": None}
    assert got["preselected_destination"] == "CA"
    assert got["intake_terms"]["CA"] == places.generic_terms()


def test_several_targets_or_unmappable_target_preselect_nothing():
    for targets in (("Ireland", "Canada"), ("Atlantis",)):
        with patch("app.pai_os_bridge.list_routes", return_value=ROUTES), \
             patch.object(places, "_standing_level", return_value="matric"), \
             patch.object(places, "_eligible_levels", return_value=None), \
             patch.object(places, "_vault_value", vault(targets=targets)):
            assert places.choice_options(None, "w1", None, today=TODAY)["preselected_destination"] is None


def test_os_down_leaves_home_only_unsupported():
    with patch("app.pai_os_bridge.list_routes", return_value=[]), \
         patch.object(places, "_standing_level", return_value="matric"), \
         patch.object(places, "_eligible_levels", return_value=None), \
         patch.object(places, "_vault_value", vault(targets=())):
        got = places.choice_options(None, "w1", None, today=TODAY)
    assert got["destinations"] == [{"code": "PK", "supported": False, "route_key": None}]


def test_places_for_supported_route_uses_the_os_list(stubs):
    with patch("app.pai_os_bridge.programmes_for",
               return_value=[{"ref": "p1", "name": "Prog", "university": "Uni"}]) as call:
        got = places.places_for(None, "w1", "IE", "bachelor", "autumn", 2027)
    call.assert_called_once_with("ie_bachelor", "autumn", 2027)
    assert got == [{"ref": "p1", "name": "Prog", "university": "Uni"}]


def test_places_for_unsupported_route_uses_stage_h(stubs):
    programs = [{"opportunity_id": f"o{i}", "title": f"T{i}", "country": "Canada"} for i in range(7)]
    programs.append({"opportunity_id": "x", "title": "Elsewhere", "country": "France"})
    with patch.object(places, "_stage_h_programs", return_value=programs), \
         patch("app.pai_os_bridge.programmes_for") as call:
        got = places.places_for(None, "w1", "CA", "bachelor", "fall", 2027)
    call.assert_not_called()
    assert [g["ref"] for g in got] == ["o0", "o1", "o2", "o3", "o4"]
    assert got[0] == {"ref": "o0", "name": "T0"}


def test_places_for_unsupported_without_stage_h_is_empty(stubs):
    with patch.object(places, "_stage_h_programs", return_value=[]):
        assert places.places_for(None, "w1", "CA", "bachelor", "fall", 2027) == []


def test_generic_terms_file():
    assert places.generic_terms() == ["winter", "summer", "spring", "autumn", "fall"]


def test_bridge_returns_empty_when_os_is_down():
    from app import pai_os_bridge as bridge

    assert bridge.list_routes() == []  # not mounted
    assert bridge.programmes_for("any", "winter", 2027) == []
    with patch("app.os.ports.plan_query.routes", side_effect=RuntimeError("boom")):
        assert bridge.list_routes() == []
    with patch("app.os.ports.plan_query.programme_list", side_effect=RuntimeError("boom")):
        assert bridge.programmes_for("any", "winter", 2027) == []


def test_bridge_maps_programme_entries():
    from app import pai_os_bridge as bridge
    from app.os.contracts.programme_list import ProgrammeEntry, ProgrammeListV1
    from app.os.contracts.route_contract import IntakeRef

    listing = ProgrammeListV1(route_key="r", intake=IntakeRef(term="winter", year=2027), programmes=[
        ProgrammeEntry(programme_ref="p1", university="Uni", name="Prog", facts_confirmed=True)])
    with patch("app.os.ports.plan_query.programme_list", return_value=listing):
        assert bridge.programmes_for("r", "winter", 2027) == [{"ref": "p1", "name": "Prog", "university": "Uni"}]


def test_fsc_student_is_offered_no_master_destination():
    """R-14: destinations intersect with the eligible levels."""
    with patch("app.pai_os_bridge.list_routes", return_value=ROUTES), \
         patch.object(places, "_standing_level", return_value="fsc"), \
         patch.object(places, "_vault_value", vault(targets=())), \
         patch.object(places, "_eligible_levels", return_value=["bachelor"]):
        got = places.choice_options(None, "w1", "electrical_engineering", today=TODAY)
    assert got["level"] == "bachelor"
    assert "DE" not in {d["code"] for d in got["destinations"]}  # DE only has a master route


def test_a_level_outside_the_eligible_ones_is_never_offered():
    with patch("app.pai_os_bridge.list_routes", return_value=ROUTES), \
         patch.object(places, "next_level", return_value="master"), \
         patch.object(places, "_standing_level", return_value="fsc"), \
         patch.object(places, "_vault_value", vault(targets=())), \
         patch.object(places, "_eligible_levels", return_value=["bachelor"]):
        got = places.choice_options(None, "w1", None, today=TODAY)
    assert got["level"] == "bachelor"
    assert "DE" not in {d["code"] for d in got["destinations"]}


def test_matric_student_is_offered_intermediate_routes_only():
    routes = ROUTES + [{"key": "pk_inter", "origin": "PK", "destination": "PK", "level": "intermediate",
                        "intake_terms": []}]
    with patch("app.pai_os_bridge.list_routes", return_value=routes), \
         patch.object(places, "_standing_level", return_value="matric"), \
         patch.object(places, "_eligible_levels", return_value=None), \
         patch.object(places, "_vault_value", vault(targets=())), \
         patch.object(places, "_eligible_levels", return_value=["intermediate"]):
        got = places.choice_options(None, "w1", None, today=TODAY)
    assert got["level"] == "intermediate"
    assert {d["code"]: d["route_key"] for d in got["destinations"]} == {"PK": "pk_inter"}
