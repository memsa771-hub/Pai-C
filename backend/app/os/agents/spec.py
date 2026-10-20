"""Agent specs: id, version, zone, model tier, tools, output, limits and retries, as data (parent §3.3).

Invariant 9: a `reader` sees outside content, so it holds no tools. Invariant 7: answer repair happens only
through output validation, at most 2 times, and agents never retry tools.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

AGENT_DIR = Path(__file__).parent


class AgentSpecError(ValueError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentLimits(_Model):
    max_readings: int = Field(ge=1)
    timeout_s: float = Field(gt=0)
    spend_usd_per_programme: float = Field(gt=0)


class AgentRetries(_Model):
    tools: Literal[0] = 0
    output: int = Field(ge=0, le=2)


class AgentSpec(_Model):
    id: str
    version: int = Field(ge=1)
    zone: Literal["reader", "actor"]
    tier: Literal["cheap", "strong"]
    tools: list[str]
    output: Literal["profile_reading"]  # the route's reading model, built from its research profile
    limits: AgentLimits
    retries: AgentRetries

    @model_validator(mode="after")
    def _reader_has_no_tools(self) -> "AgentSpec":
        if self.zone == "reader" and self.tools:
            raise ValueError(f"agent '{self.id}': a reader holds no tools (invariant 9), got {self.tools}")
        return self


def load_agent_spec(path: Path) -> AgentSpec:
    try:
        return AgentSpec.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as e:
        raise AgentSpecError(f"{path.name}: invalid YAML: {e}") from e
    except ValidationError as e:
        raise AgentSpecError(f"{path.name}: {e}") from e
