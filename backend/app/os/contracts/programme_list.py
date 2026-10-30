"""ProgrammeList v1 (Slice 8 spec S8-D14): the PAI OS programmes the Counsellor may offer for a route and intake, so
every place in an export is one PAI OS can plan. Frozen."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.os.contracts.route_contract import IntakeRef


class ProgrammeEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    programme_ref: str
    university: str
    name: str
    facts_confirmed: bool  # the facts the compiler needs are confirmed for this intake


class ProgrammeListV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.programme_list.v1"] = Field("pai.programme_list.v1", alias="schema")
    route_key: str
    intake: IntakeRef
    programmes: list[ProgrammeEntry]
