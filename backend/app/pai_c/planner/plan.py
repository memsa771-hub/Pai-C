"""Validated next-turn instructions and installed playbook selection."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.pai_c.playbooks.registry import BOOKS
from app.pai_c.possibility_titles import valid_title


class PlannedPossibility(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    title: str
    why: str = Field(min_length=1)
    evidence_item_ids: list[str] = Field(min_length=2)

    @field_validator("title")
    @classmethod
    def structural_title(cls, value):
        if not valid_title(value):
            raise ValueError("invalid possibility title")
        return value


class TurnPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    next_move: Literal["understand", "tell", "both", "care"]
    intent: str = Field(max_length=200)
    target_gap: Literal["said", "shown", "source", "pressures", "self", "sure"] | None
    give: str = Field(max_length=200)
    avoid_questions: list[str] = Field(max_length=5)
    playbooks: list[str] = Field(max_length=2)
    possibility: PlannedPossibility | None = None

    @field_validator("possibility", mode="before")
    @classmethod
    def optional_possibility(cls, value):
        try:
            return PlannedPossibility.model_validate(value) if value is not None else None
        except ValueError:
            return None

    @field_validator("playbooks")
    @classmethod
    def known_playbooks(cls, value):
        if any(id not in BOOKS for id in value):
            raise ValueError("unknown playbook")
        return value


def validate_plan(raw, wellbeing=False, *, view=None):
    plan = TurnPlan.model_validate(raw)
    if plan.possibility is not None and view is not None:
        from app.pai_c.understanding.data import load_policy, at_path
        items = {row["id"]: row for path in load_policy()["item_paths"] for row in at_path(view.data, path)}
        ids = set(plan.possibility.evidence_item_ids)
        if len(ids) < 2 or not ids <= items.keys() or not any(items[id]["kind"] in {"shown", "action"} for id in ids):
            plan = plan.model_copy(update={"possibility": None})
    return plan.model_copy(update={"next_move": "care", "target_gap": None}) if wellbeing else plan
