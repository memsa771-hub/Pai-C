"""Slice 8 Task 3: the v1 contracts are frozen (spec §2.1, S8-D15). A change is a new v2 file with both teams'
sign-off, never an edit of a v1 file."""

import hashlib
import json
from pathlib import Path

import pytest

from app.os.contracts.decision_record import DecisionRecordV1
from app.os.contracts.escalation import EscalationV1
from app.os.contracts.plan_summary import PlanSummaryV1
from app.os.contracts.programme_list import ProgrammeListV1

CONTRACTS = Path(__file__).resolve().parents[3] / "app" / "os" / "contracts"
# route_contract.v1.schema.json as on pai-os before Slice 8 (c5c7ee2): Slice 8 must not touch it
ROUTE_CONTRACT_SHA256 = "22582d12f3a960a77d5fb0a974e04fa4510452eee4687ed7bb3dab10d467a99b"


@pytest.mark.parametrize("model,name", [
    (DecisionRecordV1, "decision_record"), (PlanSummaryV1, "plan_summary"), (EscalationV1, "escalation"),
    (ProgrammeListV1, "programme_list"),
])
def test_schema_files_match_models(model, name):
    committed = json.loads((CONTRACTS / f"{name}.v1.schema.json").read_text())
    assert model.model_json_schema() == committed, f"{name} v1 changed: add a v2 file instead (S8-D15)"


def test_route_contract_untouched():
    got = hashlib.sha256((CONTRACTS / "route_contract.v1.schema.json").read_bytes()).hexdigest()
    assert got == ROUTE_CONTRACT_SHA256


def test_schema_literals():
    assert DecisionRecordV1.model_json_schema()["properties"]["schema"]["const"] == "pai.decision_record.v1"
    assert PlanSummaryV1.model_json_schema()["properties"]["schema"]["const"] == "pai.plan_summary.v1"
    assert EscalationV1.model_json_schema()["properties"]["schema"]["const"] == "pai.escalation.v1"
    assert ProgrammeListV1.model_json_schema()["properties"]["schema"]["const"] == "pai.programme_list.v1"
