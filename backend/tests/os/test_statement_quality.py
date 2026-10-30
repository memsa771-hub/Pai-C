"""Slice 5 Task 10: the Spike 4 fictional set and runner (spec S5-D11). Offline: the runner's test model only."""

import json

import pytest

from app.os.statements.config import load_statement_configs
from app.os.statements.facts_check import unsupported
from app.os.statements.run import sources
from tests.os.quality.run_statement_quality import (FICTIONAL, KINDS, _flagged, check_fictional, inputs_of, load_set,
                                                    main, score_ratings)

SET = load_set(FICTIONAL)
CFG = load_statement_configs()[SET["route"]]


def material(p: dict) -> str:
    return " ".join([*p["answers"].values(), *map(str, p["profile"].values())]).casefold()


def test_fictional_set_shape():
    personas = SET["personas"]
    assert len(personas) == 10 and len({p["id"] for p in personas}) == 10
    required = [q.id for q in CFG.questions if q.required]
    for p in personas:
        assert set(p["answers"]) <= {q.id for q in CFG.questions}
        empty = [q for q in required if not (p["answers"].get(q) or "").strip()]
        assert empty == [m for m in p["traps"]["missing"] if m in required]  # only the planted gaps
        assert p["traps"]["invented"] and p["traps"]["distinctive"]
        for phrase in p["traps"]["distinctive"]:
            assert phrase.casefold() in material(p)
        for trap in p["traps"]["invented"]:
            assert trap.casefold() not in material(p)  # a trap is never in the persona's own material
    assert {"key_project", "cgpa"} <= {m for p in personas for m in p["traps"]["missing"]}


def test_planted_inventions_flagged():
    """Every planted invention, if a draft contained it, is caught by the rule-based facts check."""
    for p in SET["personas"]:
        for kind in KINDS:
            inputs = inputs_of(p, CFG, kind)
            draft = " ".join(inputs.answers.values()) + " " + " ".join(
                f"I also have the {t}." for t in p["traps"]["invented"])
            flags = [c.text for c in unsupported(draft, sources(inputs))]
            for trap in p["traps"]["invented"]:
                assert _flagged(trap, flags), (p["id"], kind, trap)
            assert all(not _flagged(a, flags) for a in p["traps"]["distinctive"]), p["id"]  # own facts pass


def test_no_cross_persona_leak():
    personas = SET["personas"][:2]
    clean = {(p["id"], k): {"text": " ".join(p["answers"].values()), "flags": [], "over_by": 0, "labelled": True}
             for p in personas for k in KINDS}
    assert check_fictional(personas, clean)["cross_persona_leaks"] == 0
    leaked = dict(clean)
    leaked[("p01", "sop")] = {**clean[("p01", "sop")], "text": clean[("p01", "sop")]["text"] + " Sugar Diary."}
    result = check_fictional(personas, leaked)
    assert result["cross_persona_leaks"] == 1 and result["passed"] is False


def test_runner_offline_fictional_set(tmp_path, capsys):
    out = tmp_path / "s5.json"
    assert main(["--model", "test", "--set", "fictional", "--runs", "1", "--out", str(out)]) == 0
    [run] = json.loads(out.read_text())["runs"]
    assert run["passed"] and run["drafts"] == 20 and run["failed"] == 0 and run["cross_persona_leaks"] == 0
    assert run["planted_flagged"] == run["planted_in_drafts"]
    printed = capsys.readouterr().out
    for p in SET["personas"]:  # rates and counts only: no persona text is printed
        assert not any(a and a in printed for a in p["answers"].values())


def test_ratings_scored_against_the_gate(tmp_path):
    personas = SET["personas"]
    (tmp_path / "personas.yaml").write_text((FICTIONAL / "personas.yaml").read_text(encoding="utf-8"), encoding="utf-8")
    ratings = {p["id"]: {k: {"usable_after_one_edit": i < 8, "invented_facts": 0} for k in KINDS}
               for i, p in enumerate(personas)}
    import yaml

    (tmp_path / "ratings.yaml").write_text(yaml.safe_dump(ratings), encoding="utf-8")
    assert score_ratings(tmp_path, personas)["passed"] is True  # 8/10 usable, 0 invented
    ratings["p01"]["cv"]["invented_facts"] = 1
    (tmp_path / "ratings.yaml").write_text(yaml.safe_dump(ratings), encoding="utf-8")
    assert score_ratings(tmp_path, personas)["passed"] is False
    del ratings["p02"]
    (tmp_path / "ratings.yaml").write_text(yaml.safe_dump(ratings), encoding="utf-8")
    with pytest.raises(ValueError, match="not every persona"):
        score_ratings(tmp_path, personas)
