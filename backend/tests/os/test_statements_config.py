"""Slice 5 Task 1: statements as route config (spec S5-D3, S5-D12)."""

from pathlib import Path

import pytest
import yaml

from app.os.documents.types import load_document_types
from app.os.eligibility.rules import profile_keys
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.statements.config import (
    CONFIG_DIR,
    StatementConfigError,
    check_config,
    load_statement_config,
    load_statement_configs,
)

FAKE = Path(__file__).parent / "statements"
BOOKS = load_playbook_dir(PLAYBOOK_DIR) | load_playbook_dir(Path(__file__).parent / "playbooks")
KEYS = profile_keys(load_document_types())


def _germany_with(tmp_path, change) -> Path:
    data = yaml.safe_load((CONFIG_DIR / "germany_master.yaml").read_text(encoding="utf-8"))
    change(data)
    p = tmp_path / "germany_master.yaml"
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    return p


def test_germany_config_loads():
    cfg = load_statement_configs()["germany_master"]
    assert 8 <= len(cfg.questions) <= 12 and set(cfg.kinds) == {"sop", "cv"}
    assert (cfg.kinds["sop"].default_words, cfg.kinds["cv"].default_words) == (1000, 700)
    assert cfg.documents_task == "application_documents" and cfg.question("goal").required
    check_config(cfg, KEYS, BOOKS)


@pytest.mark.parametrize("n", [7, 13])
def test_question_count_bounds(tmp_path, n):
    def change(d):
        d["questions"] = [{"id": f"q{i}", "prompt": "?"} for i in range(n)]
    with pytest.raises(StatementConfigError, match="questions"):
        load_statement_config(_germany_with(tmp_path, change))


def test_duplicate_question_ids_refused(tmp_path):
    with pytest.raises(StatementConfigError, match="duplicate"):
        load_statement_config(_germany_with(tmp_path, lambda d: d["questions"][1].update(id=d["questions"][0]["id"])))


def test_unknown_profile_key_named(tmp_path):
    cfg = load_statement_config(_germany_with(tmp_path, lambda d: d["kinds"]["sop"]["profile_keys"].append("transcript.gpa")))
    with pytest.raises(StatementConfigError, match="transcript.gpa"):
        check_config(cfg, KEYS, BOOKS)


def test_unknown_documents_task_named(tmp_path):
    cfg = load_statement_config(_germany_with(tmp_path, lambda d: d.update(documents_task="write_essay")))
    with pytest.raises(StatementConfigError, match="write_essay"):
        check_config(cfg, KEYS, BOOKS)


def test_second_route_has_its_own_questions():
    ie = load_statement_configs(FAKE)["ireland_master"]
    de = load_statement_configs()["germany_master"]
    assert {q.id for q in ie.questions}.isdisjoint({q.id for q in de.questions} - {"other"})
    check_config(ie, KEYS, BOOKS)
