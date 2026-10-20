"""Slice 2 Task 10 (spec §8 test 4): replay Spike 1 reruns 9-11 through the production judge.

The readings each rerun recorded (docs/os/spikes/spike1-results/rerun9-11.json) and the snapshot pages
they read go through `trust.judge`. Against key v3, the correct rate must not fall below what Spike 1's
rules gave that run, and every fact Spike 1 confirmed that the new rules do not must name its rule.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.os.knowledge.research.trust import judge
from tests.os.quality.scoring import load_key, score
from tests.os.test_research_trust import PROFILE, Reading, _fixture_pages, _seed_programme, spec

RESULTS = Path(__file__).resolve().parents[3] / "docs" / "os" / "spikes" / "spike1-results"
FIELDS = [f.name for f in PROFILE.fields]
RULES = {"not_official", "url_not_read", "quote_not_on_page", "link_label", "value_not_in_quote", "list_not_complete",
         "scope_unclear", "scores_on_other_page", "single_reading", "readings_disagree", "cycle_unknown", "cycle_old"}


def _readings(recorded: dict, field: str) -> dict:
    out = {}
    for name, r in recorded.items():
        found = (r.get("output") or {}).get(field)
        if found:
            try:
                out[name] = getattr(Reading.model_validate({field: found}), field)
            except ValueError:
                pass  # a value the profile no longer allows: as if not found
    return out


@pytest.mark.parametrize("run", ["rerun9", "rerun10", "rerun11"])
def test_replay_spike1_reruns(run):
    pages, key = _fixture_pages(), load_key()
    results = json.loads((RESULTS / f"{run}.json").read_text())["results"]
    old, new = {}, {}
    for ref, r in results.items():
        run_pages = [pages[p["url"]] for p in r["pages"] if p.get("ok") and p["url"] in pages]
        programme = _seed_programme(ref)
        old[ref] = {f: SimpleNamespace(**{"reasons": [], **v}) for f, v in r["verdicts"].items()}
        new[ref] = {f: judge(spec(f), _readings(r["readings"], f), run_pages, programme, PROFILE, 2026) for f in FIELDS}
    before, after = score(key, old, FIELDS), score(key, new, FIELDS)
    print(f"{run}: Spike 1 rules correct {before.correct_rate:.3f} confirmed {before.confirmed_rate:.3f}; "
          f"production rules correct {after.correct_rate:.3f} confirmed {after.confirmed_rate:.3f}")
    assert after.correct_rate >= before.correct_rate
    for ref in results:
        for f in FIELDS:
            was, now = old[ref].get(f), new[ref][f]
            if was is not None and was.status == "confirmed" and now.status != "confirmed":
                named = {r.split(":", 1)[1].split(":")[0] if r[:2] in ("A:", "B:", "C:") else r.split(":")[0]
                         for r in now.reasons}
                assert named & RULES, f"{run} {ref} {f}: newly unconfirmed without a rule ({now.reasons})"


def test_quality_runner_offline(tmp_path):
    """The gate runner's wiring, free: snapshot pages and a model that finds nothing, so the gate fails."""
    from tests.os.quality import run_research_quality as q

    out = tmp_path / "q.json"
    code = q.main(["--model", "test", "--snapshot", "--runs", "1", "--only", "ovgu-eeit", "btu-cyber-security",
                   "--out", str(out)])
    data = json.loads(out.read_text())
    assert code == 1 and data["gate_passed"] is False and data["snapshot"] is True
    [run] = data["runs"]
    assert run["confirmed"] == 0 and run["scored"] > 0 and run["cost_usd"] == 0
    assert set(run["programmes"]) == {"ovgu-eeit", "btu-cyber-security"}
    assert any(p["ok"] for p in run["programmes"]["ovgu-eeit"]["pages"])  # read from the snapshot
