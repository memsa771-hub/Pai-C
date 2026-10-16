"""Transport validation for the student-facing Mirror; no topic heuristics."""

import json
from typing import Literal

import regex
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationInfo, model_validator
from typing_extensions import Annotated

from app.config import config
from app.pai_c.deep.polish import contains_blocked_script, question_count

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


class MirrorRoute(MirrorPart):
    field: str = ""
    level: str = ""
    place_preference: str = ""
    kind: str = ""


class MirrorLane(MirrorPart):
    lane: Text
    title: str = ""
    why: Text
    evidence: list[Text] = Field(default_factory=list)
    unknowns: list[Text] = Field(default_factory=list)
    strengths: list[Text] = Field(default_factory=list)
    route: MirrorRoute = Field(default_factory=MirrorRoute)


class PictureLine(MirrorPart):
    text: Text
    evidence: str
    unknown: bool

    @model_validator(mode="after")
    def evidenced(self):
        if not self.unknown and not self.evidence.strip():
            raise ValueError("picture line requires evidence or unknown=true")
        return self


class CorePicture(MirrorPart):
    you_say: PictureLine
    life_shows: PictureLine
    pressure: PictureLine
    you_want: PictureLine


class SavedCounselorMirror(MirrorPart):
    """READ contract: historical drafts remain readable without invented lines."""
    core_picture: CorePicture | None = None
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
        if "stated_goal" in lanes and "strength_based" in lanes and "test_the_dream" not in lanes:
            raise ValueError("distinct stated and strength routes require an original-dream test lane")
        if contains_blocked_script(json.dumps(self.model_dump(), ensure_ascii=False),
                                   config.PAI_LANGUAGE_BLOCKED_SCRIPTS):
            raise ValueError("mirror contains a blocked script")
        if _WORLD_NUMBER.search(self.opinion):
            raise ValueError("opinion contains numeric world-fact patterns")
        if question_count(self.spoken_reply()) != 1 or question_count(self.question) != 1:
            raise ValueError("mirror must end with one spoken confirmation question")
        return self

    def spoken_reply(self) -> str:
        picture = [line.text for line in (
            self.core_picture.you_say, self.core_picture.life_shows,
            self.core_picture.pressure, self.core_picture.you_want,
        )] if self.core_picture else []
        return "\n\n".join((self.intro, *picture, self.opinion, self.question))


class CounselorMirror(SavedCounselorMirror):
    """GENERATE contract: every new generation, including retries, must be v2."""
    core_picture: CorePicture

    @model_validator(mode="after")
    def evidenced_lanes(self):
        from app.pai_c.possibility_titles import valid_title
        for lane in self.roadmap_lanes:
            if not valid_title(lane.title):
                raise ValueError("lane requires a structurally valid direction title")
            if lane.lane in {"strength_based", "test_the_dream"} and not lane.evidence:
                raise ValueError("lane requires student evidence")
        return self

    @model_validator(mode="after")
    def no_private_quotes(self, info: ValidationInfo):
        context = info.context or {}
        # Compare free text, not the tension's status metadata.
        texts = [self.intro, self.opinion, self.question, *self.blockers]
        texts.extend(value for line in self.core_picture.model_dump().values()
                     for value in (line["text"], line["evidence"]))
        texts.extend(value for part in self.dimensions
                     for value in (part.name, part.picture, part.evidence))
        texts.extend(value for lane in self.roadmap_lanes
                     for value in (lane.title, lane.why, *lane.evidence, *lane.unknowns))
        for tension in context.get("private_gap_context", []):
            for private in (*tension["between"], tension["evidence"]):
                if private.strip() and any(private in text for text in texts):
                    raise ValueError("mirror quotes private gap context")
        return self
