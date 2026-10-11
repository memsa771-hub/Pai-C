"""Validated next-turn instructions; playbooks are deferred."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TurnPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    next_move: Literal["understand", "tell", "both", "care"]
    intent: str = Field(max_length=200)
    target_gap: Literal["said", "shown", "source", "pressures", "self", "sure"] | None
    give: str = Field(max_length=200)
    avoid_questions: list[str] = Field(max_length=5)
    playbooks: list[str]

    @field_validator("playbooks")
    @classmethod
    def known_playbooks(cls, value):
        if value:
            raise ValueError("no playbooks installed")
        return value


def validate_plan(raw, wellbeing=False):
    plan = TurnPlan.model_validate(raw)
    return plan.model_copy(update={"next_move": "care", "target_gap": None}) if wellbeing else plan
