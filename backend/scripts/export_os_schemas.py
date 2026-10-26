"""Writes the Slice 8 v1 contract schema files from their models: python scripts/export_os_schemas.py

Run it once when a contract is first added. A v1 file never changes after that (tests/os/contracts/test_frozen.py):
a change is a new v2 model and file. route_contract.v1.schema.json is older and is not written here."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.os.contracts.decision_record import DecisionRecordV1  # noqa: E402
from app.os.contracts.escalation import EscalationV1  # noqa: E402
from app.os.contracts.plan_summary import PlanSummaryV1  # noqa: E402
from app.os.contracts.programme_list import ProgrammeListV1  # noqa: E402

CONTRACTS = Path(__file__).resolve().parents[1] / "app" / "os" / "contracts"
MODELS = {"decision_record": DecisionRecordV1, "plan_summary": PlanSummaryV1, "escalation": EscalationV1,
          "programme_list": ProgrammeListV1}


def main() -> None:
    for name, model in MODELS.items():
        path = CONTRACTS / f"{name}.v1.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2) + "\n")
        print(f"wrote {path.relative_to(CONTRACTS.parents[2])}")


if __name__ == "__main__":
    main()
