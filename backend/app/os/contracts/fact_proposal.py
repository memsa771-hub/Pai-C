"""Fact proposal v1 (P1-T7 D-y8, master §9.2 `FactProposalSink`): the facts a student confirmed on one document, offered
to the Counsellor's Vault. Only fields whose document type declares a `fact:` key are ever listed (marks, GPA and
scale, test scores): never a name, date of birth or passport value. `document_ref` is the Counsellor file ID, or
`os:<id>` for a document whose bytes only PAI OS holds. The Vault reconciler decides what is written. Frozen: a change
is a new version file."""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.os.contracts.student_facts import FACT_KEY


class ProposedFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str = Field(pattern=FACT_KEY)
    value: str | int | float


class FactProposalV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)

    schema_: Literal["pai.fact_proposal.v1"] = Field("pai.fact_proposal.v1", alias="schema")
    key: Annotated[str, Field(pattern=r"^[a-z0-9_:.-]+$")]
    student_ref: str = Field(min_length=1)
    document_ref: str = Field(min_length=1)
    doc_type: str = Field(min_length=1)
    confirmed_at: AwareDatetime
    facts: list[ProposedFact] = Field(min_length=1, max_length=20)

    @field_validator("facts")
    @classmethod
    def _unique(cls, facts: list[ProposedFact]) -> list[ProposedFact]:
        keys = [f.key for f in facts]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate fact key in facts")
        return facts
