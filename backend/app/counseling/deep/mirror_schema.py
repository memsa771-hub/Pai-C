"""Transport validation for the student-facing Mirror; no topic heuristics."""

import json
from typing import Literal

import regex
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from typing_extensions import Annotated

from app.config import config
from app.counseling.deep.polish import contains_blocked_script, question_count

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
DIMENSION_KEYS = frozenset({
    "education", "stated_goal", "wish_source", "done", "strengths",
    "holds_back", "drives", "family", "limits",
})
# Unicode currency symbols, generic three-letter currency codes, percentages,
# ratios and decimal scores. No country, institution or subject vocabulary.
_NUMBER = r"\d+(?:[.,]\d+)?"
_WORLD_NUMBER = regex.compile(
    rf"(?:\p{{Sc}}\s*{_NUMBER}|{_NUMBER}\s*\p{{Sc}}|"
    rf"\b[A-Z]{{3}}\s*{_NUMBER}|{_NUMBER}\s*[A-Z]{{3}}\b|"
    rf"{_NUMBER}\s*[%\u066a\ufe6a\uff05]|"
    rf"{_NUMBER}\s*[/\uff1a:]\s*{_NUMBER}|\b\d+[.,]\d+\b)"
)


class MirrorPart(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class MirrorDimension(MirrorPart):
    key: Text
    name: Text
    picture: Text
    evidence: str = ""
    unknown: bool = False

    @model_validator(mode="after")
    def evidenced(self):
        if not self.unknown and not self.evidence.strip():
            raise ValueError("dimension requires evidence or unknown=true")
        return self


class MirrorLane(MirrorPart):
    lane: Text
    why: Text
    strengths: list[Text] = Field(default_factory=list)


class CounselorMirror(MirrorPart):
    intro: Text
    confidence: Literal["full", "focused", "light"]
    dimensions: list[MirrorDimension]
    blockers: list[Text] = Field(min_length=2, max_length=5)
    opinion: Text
    question: Text
    roadmap_lanes: list[MirrorLane] = Field(min_length=4, max_length=5)

    @model_validator(mode="after")
    def valid_contract(self):
        keys = [part.key for part in self.dimensions]
        if len(keys) != len(DIMENSION_KEYS) or set(keys) != DIMENSION_KEYS:
            raise ValueError("mirror requires each dimension key exactly once")
        lanes = [part.lane for part in self.roadmap_lanes]
        if len(set(lanes)) != len(lanes):
            raise ValueError("roadmap lane keys must be unique")
        if contains_blocked_script(json.dumps(self.model_dump(), ensure_ascii=False),
                                   config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
            raise ValueError("mirror contains a blocked script")
        if _WORLD_NUMBER.search(self.opinion):
            raise ValueError("opinion contains numeric world-fact patterns")
        if question_count(self.spoken_reply()) != 1 or question_count(self.question) != 1:
            raise ValueError("mirror must end with one spoken confirmation question")
        return self

    def spoken_reply(self) -> str:
        return "\n\n".join((self.intro, self.opinion, self.question))
