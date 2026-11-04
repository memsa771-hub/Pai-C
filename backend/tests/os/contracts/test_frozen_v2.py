"""P1-T1: the v2 and new v1 contract files are frozen (P1 spec §3.9, master §9.1). A change is a new version file."""

import json
from pathlib import Path

import pytest
import yaml

from app.os.contracts.choice_request import ChoiceRequestV1
from app.os.contracts.decision_record_v2 import DecisionRecordV2
from app.os.contracts.escalation_v2 import EscalationV2
from app.os.contracts.os_event import OsEventV1
from app.os.contracts.plan_view import PlanViewV1
from app.os.contracts.route_contract_v2 import RouteContractV2
from app.os.contracts.student_facts import StudentFactsV1
from app.os.contracts.vault_event import VaultEventV1

pytestmark = pytest.mark.req("R-41")

CONTRACTS = Path(__file__).resolve().parents[3] / "app" / "os" / "contracts"
SAMPLES = CONTRACTS / "samples" / "v2"
MODELS = {"decision_record.v2": DecisionRecordV2, "route_contract.v2": RouteContractV2,
          "escalation.v2": EscalationV2, "plan_view.v1": PlanViewV1, "os_event.v1": OsEventV1,
          "choice_request.v1": ChoiceRequestV1, "student_facts.v1": StudentFactsV1,
          "vault_event.v1": VaultEventV1}


@pytest.mark.parametrize("stem", sorted(MODELS))
def test_v2_schema_files_match_models(stem):
    committed = json.loads((CONTRACTS / f"{stem}.schema.json").read_text())
    assert MODELS[stem].model_json_schema() == committed, f"{stem} changed: add a new version file instead"


@pytest.mark.parametrize("stem", sorted(set(MODELS) - {"route_contract.v2"}))
def test_v2_schema_literals(stem):
    name, version = stem.rsplit(".", 1)
    assert MODELS[stem].model_json_schema()["properties"]["schema"]["const"] == f"pai.{name}.{version}"


def test_samples_validate():
    listed = yaml.safe_load((SAMPLES / "valid.yaml").read_text())
    assert {e["file"] for e in listed} == {p.name for p in SAMPLES.glob("*.json")}
    for entry in listed:
        MODELS[entry["contract"]].model_validate(json.loads((SAMPLES / entry["file"]).read_text()))
