"""Slice 8 Task 3: the decision record export v1 and the other v1 contracts (spec §2.1, S8-D5, S8-D8). Fictional."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.os.contracts.decision_record import DecisionRecordV1
from app.os.contracts.escalation import EscalationV1
from app.os.contracts.plan_summary import PlanSummaryV1
from app.os.contracts.programme_list import ProgrammeListV1
from app.os.contracts.route_contract import RouteContract

SAMPLES = Path(__file__).resolve().parents[3] / "app" / "os" / "contracts" / "samples"


def export(**over) -> dict:
    base = {"schema": "pai.decision_record.v1", "decision_id": "d-1", "journey_id": "j-1", "student_ref": "ws-1",
            "chosen_at": "2027-01-10T09:00:00+05:00", "authorized_at": "2027-01-10T09:01:00+05:00",
            "origin_country": "PK", "destination_country": "DE", "level": "master",
            "target_intake": {"term": "winter", "year": 2027},
            "programmes": [{"programme_ref": "prog-a", "rank": 1}, {"programme_ref": "prog-b", "rank": 2}]}
    return {**base, **over}


def test_external_ref_format():
    d = DecisionRecordV1.model_validate(export(destination_country="de"))
    assert d.external_ref == "j-1:DE:master"  # journey + destination + level (S8-D8)


def test_to_route_contract_counsellor_source():
    c = DecisionRecordV1.model_validate(export()).to_route_contract()
    assert isinstance(c, RouteContract)
    assert (c.contract_version, c.source, c.external_ref, c.student_ref) == ("1", "counsellor", "j-1:DE:master", "ws-1")
    assert (c.origin_country, c.destination_country, c.level) == ("PK", "DE", "master")
    assert [(p.programme_ref, p.rank) for p in c.programmes] == [("prog-a", 1), ("prog-b", 2)]
    assert (c.target_intake.term, c.target_intake.year) == ("winter", 2027)


def test_six_places_rejected():
    six = [{"programme_ref": f"p{n}", "rank": n} for n in range(1, 7)]
    with pytest.raises(ValidationError, match="at most 5"):
        DecisionRecordV1.model_validate(export(programmes=six))
    assert len(DecisionRecordV1.model_validate(export(programmes=six[:5])).programmes) == 5


def test_nationality_optional_and_not_in_route_contract():
    assert DecisionRecordV1.model_validate(export()).nationality is None
    d = DecisionRecordV1.model_validate(export(nationality="pk"))
    assert d.nationality == "PK"
    assert "nationality" not in d.to_route_contract().model_dump()


def test_authorized_at_optional_so_it_can_be_refused():
    assert DecisionRecordV1.model_validate(export(authorized_at=None)).authorized_at is None


@pytest.mark.parametrize("bad,msg", [
    ({"schema": "pai.decision_record.v2"}, "pai.decision_record.v1"),
    ({"origin_country": "PAK"}, "two-letter"),
    ({"nationality": "Pakistani"}, "two-letter"),
    ({"level": "degree"}, "level"),
    ({"chosen_at": "2027-01-10T09:00:00"}, "timezone"),  # invariant 13
    ({"programmes": []}, "at least 1"),
    ({"programmes": [{"programme_ref": "a", "rank": 1}, {"programme_ref": "a", "rank": 2}]}, "duplicate programme"),
    ({"programmes": [{"programme_ref": "a", "rank": 2}]}, "ranks must be 1..n"),
    ({"truth_map": {}}, "Extra inputs"),  # never the Counsellor's private notes
])
def test_rejections(bad, msg):
    with pytest.raises(ValidationError, match=msg):
        DecisionRecordV1.model_validate(export(**bad))


def test_spring_and_fall_terms_allowed():
    for term in ("spring", "fall"):
        assert DecisionRecordV1.model_validate(export(target_intake={"term": term, "year": 2028})).target_intake.term == term


def test_summary_holds_at_most_three_deadlines():
    s = json.loads((SAMPLES / "summary.json").read_text())
    PlanSummaryV1.model_validate(s)
    s["next_deadlines"] = s["next_deadlines"] * 4
    with pytest.raises(ValidationError, match="at most 3"):
        PlanSummaryV1.model_validate(s)
    with pytest.raises(ValidationError, match="state"):
        PlanSummaryV1.model_validate({**json.loads((SAMPLES / "summary.json").read_text()), "state": "late"})


def test_escalation_reasons_closed():
    e = json.loads((SAMPLES / "escalation.json").read_text())
    assert EscalationV1.model_validate(e).reason == e["reason"]
    with pytest.raises(ValidationError, match="reason"):
        EscalationV1.model_validate({**e, "reason": "cost"})  # a later version (S8-D12)


def test_programme_list_roundtrip():
    got = ProgrammeListV1.model_validate({"route_key": "germany_master", "intake": {"term": "winter", "year": 2027},
                                          "programmes": [{"programme_ref": "prog-a", "university": "University",
                                                          "name": "Programme A", "facts_confirmed": True}]})
    assert got.schema_ == "pai.programme_list.v1"
    assert got.model_dump(mode="json", by_alias=True)["schema"] == "pai.programme_list.v1"


def test_outbound_dump_uses_schema_key():
    raised = datetime(2027, 1, 10, tzinfo=timezone.utc)
    e = EscalationV1(key="escalation:1", case_id=1, journey_id="j-1", student_ref="ws-1", reason="blocking_gap",
                     note="A fixed sentence.", raised_at=raised)
    assert e.model_dump(mode="json", by_alias=True)["schema"] == "pai.escalation.v1"


def test_samples_validate():
    expected = yaml.safe_load((SAMPLES / "expected.yaml").read_text())
    listed = {e["file"] for e in expected["exports"]} | set(expected["valid"])
    assert listed == {p.name for p in SAMPLES.glob("*.json")}  # every sample is listed with its result
    for e in expected["exports"]:
        d = DecisionRecordV1.model_validate(json.loads((SAMPLES / e["file"]).read_text()))
        assert d.student_ref.startswith("ws-sample")  # fictional
        assert e["result"] in ("planned", "revised", "replaced") or e["result"].startswith("refused:")
    models = {"summary.json": PlanSummaryV1, "escalation.json": EscalationV1}
    for name in expected["valid"]:
        models[name].model_validate(json.loads((SAMPLES / name).read_text()))
