"""Vault event v1 (master §9.1, P1 spec §3.9): a notice from the Counsellor that facts of a student changed. Keys
only, never values; PAI OS reads student_facts for the values. Frozen: a change is a new version file."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from app.os.contracts.student_facts import FACT_KEY


class VaultEventV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.vault_event.v1"] = Field("pai.vault_event.v1", alias="schema")
    key: str = Field(min_length=1)
    student_ref: str = Field(min_length=1)
    vault_version: int = Field(ge=1)
    kind: Literal["fact_changed"]
    keys: list[Annotated[str, Field(pattern=FACT_KEY)]] = Field(min_length=1)
    at: AwareDatetime
