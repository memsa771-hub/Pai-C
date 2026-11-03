"""Branch rulesets (docs/connect/rulesets) stay in step with the CI jobs and master spec 13.4 (R-59)."""
import json
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.req("R-59")

REPO = Path(__file__).resolve().parents[2]
RULESETS = REPO / "docs" / "connect" / "rulesets"
WORKFLOWS = REPO / ".github" / "workflows"


def _ruleset(name):
    return json.loads((RULESETS / f"{name}.json").read_text(encoding="utf-8"))


def _rule(ruleset, kind):
    (rule,) = [r for r in ruleset["rules"] if r["type"] == kind]
    return rule.get("parameters", {})


def _pr_jobs_for(branch):
    """Job ids of the workflows that run on pull requests into `branch`."""
    jobs = set()
    for path in WORKFLOWS.glob("*.yml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = data.get("on", data.get(True)) or {}
        if "pull_request" not in triggers:
            continue
        branches = (triggers["pull_request"] or {}).get("branches")
        if branches is None or branch in branches:
            jobs |= set(data["jobs"])
    return jobs


@pytest.mark.parametrize("branch", ["pai-connect", "pai-merge"])
def test_required_checks_are_jobs_that_run_for_the_branch(branch):
    checks = {c["context"] for c in _rule(_ruleset(branch), "required_status_checks")["required_status_checks"]}
    assert checks
    assert checks <= _pr_jobs_for(branch), checks - _pr_jobs_for(branch)


@pytest.mark.parametrize("branch", ["pai-connect", "pai-merge"])
def test_every_ci_job_is_required(branch):
    checks = {c["context"] for c in _rule(_ruleset(branch), "required_status_checks")["required_status_checks"]}
    assert _pr_jobs_for(branch) <= checks


@pytest.mark.parametrize("branch, method", [("pai-connect", "squash"), ("pai-merge", "merge")])
def test_ruleset_targets_branch_and_requires_code_owner_review(branch, method):
    ruleset = _ruleset(branch)
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == [f"refs/heads/{branch}"]
    pr = _rule(ruleset, "pull_request")
    assert pr["require_code_owner_review"] is True
    assert pr["required_approving_review_count"] >= 1
    assert pr["dismiss_stale_reviews_on_push"] is True
    assert pr["allowed_merge_methods"] == [method]
    assert {r["type"] for r in ruleset["rules"]} >= {"deletion", "non_fast_forward"}


def test_freeze_is_required_only_where_it_runs():
    assert "freeze" in _pr_jobs_for("pai-connect")
    assert "freeze" not in _pr_jobs_for("pai-merge")
