"""CODEOWNERS routes Counsellor paths to the Counsellor lead only (R-43, master spec section 10)."""
from fnmatch import fnmatch
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("R-43")

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEOWNERS = REPO_ROOT / ".github" / "CODEOWNERS"


def owners_for(path: str, codeowners_text: str) -> list[str]:
    """Owners of path: the last matching pattern wins.

    A pattern starting with "/" anchors at the repo root; a trailing "/" matches
    the directory and everything under it.
    """
    owners: list[str] = []
    for raw in codeowners_text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        pattern, *who = line.split()
        anchored = pattern.startswith("/")
        pat = pattern.lstrip("/")
        if pat.endswith("/"):
            hit = path.startswith(pat) if anchored else (pat in path or path.startswith(pat))
        elif anchored:
            hit = fnmatch(path, pat)
        else:
            hit = fnmatch(path.rsplit("/", 1)[-1], pat) or fnmatch(path, pat)
        if hit:
            owners = who
    return owners


@pytest.mark.parametrize("path", [
    "backend/app/pai_c/deep/analysis.py",
    "backend/app/pai_os_bridge.py",
    "backend/app/config.py",
    "frontend/components/counselor/workspace/inline-card.tsx",
    "scripts/check_freeze.py",
    "scripts/check_traceability.py",
    ".github/workflows/freeze.yml",
    "docs/requirements/connection.yaml",
    "docs/counselor/COUNSELOR_V3_PROMPTS.md",
])
def test_counsellor_lead_owns_counsellor_paths(path):
    assert owners_for(path, CODEOWNERS.read_text()) == ["@memsa771-hub"]


def test_os_paths_keep_os_owners():
    assert owners_for("backend/app/os/kernel/x.py", CODEOWNERS.read_text()) == ["@10Faheem", "@MusawirKtk"]


def test_ci_workflow_keeps_shared_owners():
    # Overlaps the earlier /.github/ rule; pins last-match-wins.
    assert owners_for(".github/workflows/ci.yml", CODEOWNERS.read_text()) == [
        "@10Faheem", "@MusawirKtk", "@memsa771-hub"]
