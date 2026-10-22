"""Statements as route data (Slice 5 spec S5-D3, S5-D12): the interview, the rubric per kind, the default limits,
the profile keys each kind may use, and the plan task that approval completes. Python knows only the kinds."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CONFIG_DIR = Path(__file__).parent
Kind = Literal["sop", "cv"]


class StatementConfigError(ValueError):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Question(_Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    prompt: str
    hint: str = ""
    required: bool = True


class Rubric(_Model):
    criteria: list[str] = Field(min_length=1)


class KindConfig(_Model):
    rubric: Rubric
    default_words: int = Field(gt=0)
    profile_keys: list[str] = []  # the confirmed profile values this kind may use ("<doc_type>.<field>")


class StatementConfig(_Model):
    route_key: str
    questions: list[Question] = Field(min_length=8, max_length=12)
    kinds: dict[Kind, KindConfig]
    documents_task: str | None = None  # the plan task approval completes (S5-D8)

    @model_validator(mode="after")
    def _unique_ids(self) -> "StatementConfig":
        ids = [q.id for q in self.questions]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"duplicate question ids {dupes}")
        return self

    def question(self, qid: str) -> Question | None:
        return next((q for q in self.questions if q.id == qid), None)


def load_statement_config(path: Path) -> StatementConfig:
    try:
        return StatementConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as e:
        raise StatementConfigError(f"{path.name}: invalid YAML: {e}") from e
    except ValidationError as e:
        raise StatementConfigError(f"{path.name}: {e}") from e


def load_statement_configs(directory: Path = CONFIG_DIR) -> dict[str, StatementConfig]:
    out: dict[str, StatementConfig] = {}
    for path in sorted(directory.glob("*.yaml")):
        cfg = load_statement_config(path)
        if cfg.route_key in out:
            raise StatementConfigError(f"{path.name}: a second config for route {cfg.route_key}")
        out[cfg.route_key] = cfg
    return out


def check_config(cfg: StatementConfig, profile_keys: set[str], books) -> None:
    """Every profile key, the route and its documents task must exist. Raises StatementConfigError naming them."""
    where = f"statements for {cfg.route_key}"
    routes = {key: b for (key, _), b in books.items()}
    if cfg.route_key not in routes:
        raise StatementConfigError(f"{where}: unknown route '{cfg.route_key}'")
    unknown = sorted({k for kc in cfg.kinds.values() for k in kc.profile_keys} - profile_keys)
    if unknown:
        raise StatementConfigError(f"{where}: unknown profile keys {unknown}")
    if cfg.documents_task and cfg.documents_task not in {t.template_key for t in routes[cfg.route_key].tasks}:
        raise StatementConfigError(f"{where}: documents_task '{cfg.documents_task}' is not a task of the route")
