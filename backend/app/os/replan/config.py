"""Per-route replan settings (Slice 7 spec §2): `app/os/replan/<route>.yaml`. A route without a file uses the
defaults. Python holds no route's values (invariant 12)."""

from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPLAN_DIR = Path(__file__).parent


class ReplanConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    route_key: str = ""
    min_programmes: int = Field(default=1, ge=1)  # below this after a rejection, the rules propose a swap


def load_replan_configs(directory: Path = REPLAN_DIR) -> dict[str, ReplanConfig]:
    out: dict[str, ReplanConfig] = {}
    for path in sorted(directory.glob("*.yaml")):
        cfg = ReplanConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        out[cfg.route_key] = cfg
    return out
