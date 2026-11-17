"""ProgrammeList v2 (P2 spec P2-D27, §4.1; master R-34, R-35d): v1 plus each place's coverage level, its region code
(R-76) and whether PAI can run it yet. v1 stays frozen (`programme_list.py`). Frozen: a change is a new version."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.os.contracts.route_contract import IntakeRef


class ProgrammeEntryV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    programme_ref: str
    university: str
    name: str
    facts_confirmed: bool  # as v1: the facts the compiler needs are confirmed for this intake
    coverage_level: Literal["listed", "researched", "verified"]
    region: str | None = Field(None, pattern=r"^[a-z][a-z0-9_]*$")
    not_run_yet: bool = False  # "PAI can't run this place yet" (R-35d)


class ProgrammeListV2(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.programme_list.v2"] = Field("pai.programme_list.v2", alias="schema")
    route_key: str
    intake: IntakeRef
    programmes: list[ProgrammeEntryV2]
