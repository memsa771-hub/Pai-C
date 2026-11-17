"""Freeze check for Counsellor prompts, policy and model settings (R-43, master spec section 10).

Fails when a change touches a frozen Counsellor file or a model setting in
backend/app/config.py, unless the PR has the freeze-exception label and names an R-ID.
Stdlib only.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path

FROZEN_PATTERNS: tuple[re.Pattern, ...] = tuple(
    re.compile(p)
    for p in (
        r"^backend/app/pai_c/.*\.md$",
        r"^backend/app/pai_c/deep/",
        r"^backend/app/pai_c/(planner|policy|voice)/prompts/",
        r"^backend/app/pai_c/playbooks/",
        r"^backend/app/pai_c/policy/actions/",
        r"^backend/app/pai_c/policy/[^/]+\.json$",
        r"^docs/counselor/COUNSELOR_V3_PROMPTS\.md$",
    )
)

MODEL_SETTING = re.compile(
    r"^(PAI_MODEL|PAI_COUNSELOR_\w+|PAI_\w+_MODEL|PAI_\w+_REASONING_EFFORT|PAI_\w+_MAX_TOKENS)$"
)

CONFIG_PATH = "backend/app/config.py"
REQUIREMENTS_PATH = "docs/requirements/connection.yaml"
FAIL_MESSAGE = (
    "Frozen Counsellor files or model settings changed (master spec section 10). Add the "
    "freeze-exception label and a known R-ID to the PR, with a replay and the Counsellor lead's approval."
)


def frozen_files(changed: Iterable[str]) -> list[str]:
    return sorted({f for f in changed if any(p.search(f) for p in FROZEN_PATTERNS)})


def _settings(src: str) -> dict[str, str]:
    out: dict[str, str] = {}
    if not src.strip():
        return out
    for cls in ast.walk(ast.parse(src)):
        if not isinstance(cls, ast.ClassDef):
            continue
        for node in cls.body:
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets = [node.target]
            else:
                continue
            if node.value is None:
                continue
            for t in targets:
                if MODEL_SETTING.match(t.id):
                    out[t.id] = ast.unparse(node.value)
    return out


def changed_model_settings(old_src: str, new_src: str) -> list[str]:
    old, new = _settings(old_src), _settings(new_src)
    return sorted(n for n in old.keys() | new.keys() if old.get(n) != new.get(n))


def exception_allowed(labels: list[str], pr_text: str, known_rids: set[str]) -> bool:
    """The label plus at least one R-ID in the text that is a real requirement."""
    if "freeze-exception" not in labels:
        return False
    return any(r in known_rids for r in re.findall(r"\bR-\d{2}\b", pr_text))


def known_requirement_ids(root: str) -> set[str]:
    """R-IDs listed under `requirements:` (two-space-indented keys); none if the file is missing."""
    path = Path(root) / REQUIREMENTS_PATH
    if not path.is_file():
        return set()
    return set(re.findall(r"^  (R-\d{2}):", path.read_text(encoding="utf-8"), re.M))


def _git(root: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)


def _config_at(root: str, rev: str) -> str:
    show = _git(root, "show", f"{rev}:{CONFIG_PATH}")
    return show.stdout if show.returncode == 0 else ""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base", required=True, help="base ref to diff against")
    args = ap.parse_args(argv)

    top = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True)
    if top.returncode != 0:
        print("not inside a git repository", file=sys.stderr)
        return 2
    root = top.stdout.strip()

    diff = _git(root, "diff", "--name-only", "--no-renames", f"{args.base}...HEAD")
    if diff.returncode != 0:
        print(diff.stderr.strip(), file=sys.stderr)
        return 2
    files = frozen_files(diff.stdout.splitlines())

    mb = _git(root, "merge-base", args.base, "HEAD")
    if mb.returncode != 0:
        print(mb.stderr.strip(), file=sys.stderr)
        return 2
    base_rev = mb.stdout.strip()
    try:
        settings = changed_model_settings(_config_at(root, base_rev), _config_at(root, "HEAD"))
    except SyntaxError:
        for rev in (base_rev, "HEAD"):
            try:
                _settings(_config_at(root, rev))
            except SyntaxError:
                print(f"{CONFIG_PATH} does not parse at {rev}", file=sys.stderr)
                break
        return 2

    if not files and not settings:
        print("Freeze check: no frozen Counsellor file or model setting changed.")
        return 0

    if files:
        print("Frozen files changed:")
        for f in files:
            print(f"  {f}")
    if settings:
        print("Model settings changed:")
        for s in settings:
            print(f"  {s}")

    labels = [x.strip() for x in os.environ.get("PR_LABELS", "").split(",") if x.strip()]
    if exception_allowed(labels, os.environ.get("PR_TEXT", ""), known_requirement_ids(root)):
        print("freeze-exception label and known R-ID present: allowed.")
        return 0
    print(FAIL_MESSAGE)
    return 1


if __name__ == "__main__":
    sys.exit(main())
