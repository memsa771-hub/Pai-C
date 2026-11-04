"""Writes the contract schema files (v1 from Slice 8, v2 and later from P1) from their models: python scripts/export_os_schemas.py

Run it once when a contract is first added. A written file never changes after that (tests/os/contracts/test_frozen.py):
a change is a new version model and file. route_contract.v1.schema.json is older and is not written here."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.os.contracts.decision_record import DecisionRecordV1  # noqa: E402
from app.os.contracts.decision_record_v2 import DecisionRecordV2  # noqa: E402
from app.os.contracts.escalation import EscalationV1  # noqa: E402
from app.os.contracts.plan_summary import PlanSummaryV1  # noqa: E402
from app.os.contracts.programme_list import ProgrammeListV1  # noqa: E402
from app.os.contracts.route_contract_v2 import RouteContractV2  # noqa: E402

CONTRACTS = Path(__file__).resolve().parents[1] / "app" / "os" / "contracts"
# file stem (name.vN) -> model; the file is <stem>.schema.json
MODELS = {"decision_record.v1": DecisionRecordV1, "plan_summary.v1": PlanSummaryV1, "escalation.v1": EscalationV1,
          "programme_list.v1": ProgrammeListV1, "decision_record.v2": DecisionRecordV2,
          "route_contract.v2": RouteContractV2}


def main() -> None:
    for name, model in MODELS.items():
        path = CONTRACTS / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print(f"wrote {path.relative_to(CONTRACTS.parents[2])}")


if __name__ == "__main__":
    main()
