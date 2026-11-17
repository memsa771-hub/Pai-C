"""P1-T1: the v2 and new v1 contract files are frozen (P1 spec §3.9, master §9.1). A change is a new version file."""

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from app.os.contracts.choice_request import ChoiceRequestV1
from app.os.contracts.decision_record_v2 import DecisionRecordV2
from app.os.contracts.escalation_v2 import EscalationV2
from app.os.contracts.fact_conflicts import FactConflictsV1
from app.os.contracts.fact_proposal import FactProposalV1
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
          "vault_event.v1": VaultEventV1, "fact_proposal.v1": FactProposalV1,
          "fact_conflicts.v1": FactConflictsV1}


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


# Each v2 / new schema file pinned by hash: editing a model and re-running the export script must fail here.
SCHEMA_SHA256 = {
    "decision_record.v2":
        "1425137e0262dc0a83d8e362e9d8132d18ad660b2bb01cbbe4ed453af2e542ae",
    "route_contract.v2":
        "eb666edafa466c2788224dd3f12bae76420c01f059210d2d0ab5d34b20f53201",
    "escalation.v2":
        "d37d801a3730b2a7168b4ed6bbe47effd6e382bd00d185edb7323bc2786120bf",
    "plan_view.v1":
        "cc6c442f250a42bf6b936d006949d8a1720196256b30d896241f515a533b3923",
    "os_event.v1":
        "2e500ef94d4f68cb54529103ba6eccbe800e10850d35f97660e58524a4183908",
    "choice_request.v1":
        "e72ec05cdc0303d3e16d685f1b140526a637f5b85615d2bc7d1120b20be02ba4",
    "student_facts.v1":
        "dedcb360ef345efc55ccc6f116c65a51085b7ff9919a7c10b00bba99c9e91a04",
    "vault_event.v1":
        "b25d69e0009ea3efae78f19a4bea1c6773344e195abfc009435e0fae8d23c69d",
    "fact_proposal.v1":
        "e6303f9d5b5b7930edc0c9e0793001a797838cbfca637332f919578346b9cac1",
    "fact_conflicts.v1":
        "359e6772063bcf0d17f5b34c6f8644806b57ff6387bb0cda704fb1bb65edc877",
}


@pytest.mark.parametrize("stem", sorted(MODELS))
def test_v2_schema_file_hash_pinned(stem):
    got = hashlib.sha256((CONTRACTS / f"{stem}.schema.json").read_bytes()).hexdigest()
    assert got == SCHEMA_SHA256[stem], f"{stem} changed: add a new version file instead"
