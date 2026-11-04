"""P1-T1: the v2 contracts beside the frozen v1 files (P1 spec §3.9, R-41). Fictional data."""

import pytest
from pydantic import ValidationError

from app.os.contracts.decision_record import DecisionRecordV1
from app.os.contracts.decision_record_v2 import DecisionRecordV2
from app.os.contracts.route_contract_v2 import RouteContractV2

pytestmark = pytest.mark.req("R-41")


def export_v2(**over) -> dict:
    base = {"schema": "pai.decision_record.v2", "decision_id": "d-1", "journey_id": "j-1", "student_ref": "ws-1",
            "decision_version": 1, "status": "chosen",
            "chosen_at": "2027-01-10T09:00:00+05:00", "authorized_at": "2027-01-10T09:01:00+05:00",
            "origin_country": "PK", "destination_country": "DE", "level": "master", "os_supported": True,
            "target_intake": {"term": "winter", "year": 2027},
            "programmes": [{"programme_ref": "prog-a", "rank": 1}, {"programme_ref": "prog-b", "rank": 2}]}
    return {**base, **over}


def test_v2_accepts_intermediate_v1_rejects_it():
    assert DecisionRecordV2.model_validate(export_v2(level="intermediate")).level == "intermediate"
    v1 = {k: v for k, v in export_v2(level="intermediate").items()
          if k not in ("decision_version", "status", "os_supported")}
    with pytest.raises(ValidationError):
        DecisionRecordV1.model_validate({**v1, "schema": "pai.decision_record.v1"})


def test_withdrawn_needs_no_places_or_intake():
    d = DecisionRecordV2.model_validate(export_v2(status="withdrawn", programmes=[], target_intake=None))
    with pytest.raises(ValueError):
        d.to_route_contract()


def test_chosen_supported_needs_places_and_intake():
    with pytest.raises(ValidationError):
        DecisionRecordV2.model_validate(export_v2(programmes=[]))
    with pytest.raises(ValidationError):
        DecisionRecordV2.model_validate(export_v2(target_intake=None))


def test_chosen_unsupported_allows_no_places():
    d = DecisionRecordV2.model_validate(export_v2(os_supported=False, programmes=[]))
    assert d.programmes == []
    with pytest.raises(ValueError):
        d.to_route_contract()


def test_places_unique_and_ranked():
    dup = [{"programme_ref": "a", "rank": 1}, {"programme_ref": "a", "rank": 2}]
    with pytest.raises(ValidationError, match="duplicate programme"):
        DecisionRecordV2.model_validate(export_v2(programmes=dup))
    gap = [{"programme_ref": "a", "rank": 1}, {"programme_ref": "b", "rank": 3}]
    with pytest.raises(ValidationError, match="ranks must be 1..n"):
        DecisionRecordV2.model_validate(export_v2(programmes=gap))
    six = [{"programme_ref": f"p{n}", "rank": n} for n in range(1, 7)]
    with pytest.raises(ValidationError, match="at most 5"):
        DecisionRecordV2.model_validate(export_v2(programmes=six))


def test_version_starts_at_one():
    with pytest.raises(ValidationError):
        DecisionRecordV2.model_validate(export_v2(decision_version=0))


def test_route_contract_v2_from_decision():
    d = DecisionRecordV2.model_validate(export_v2(level="intermediate", origin_country="pk", destination_country="pk"))
    c = d.to_route_contract()
    assert isinstance(c, RouteContractV2)
    assert (c.contract_version, c.source, c.level) == ("2", "counsellor", "intermediate")
    assert c.external_ref == "j-1:PK:intermediate"
    assert c.dedupe_key == "counsellor:j-1:PK:intermediate:2"


def test_extra_fields_forbidden():
    with pytest.raises(ValidationError, match="Extra inputs"):
        DecisionRecordV2.model_validate(export_v2(truth_map={}))
