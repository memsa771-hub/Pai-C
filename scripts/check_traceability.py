#!/usr/bin/env python3
"""Requirement traceability check (master spec section 13.1, R-57).

Reads docs/requirements/connection.yaml, collects the R-ID tags found in the
tests, and fails when a required requirement has no tagged test or a tag names
an unknown requirement. See the header of the yaml for how `built` works.

    python scripts/check_traceability.py              # CI check
    python scripts/check_traceability.py --gate P1    # also require all of P1
    python scripts/check_traceability.py --report P1  # markdown table for P1
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
YAML_PATH = REPO / "docs" / "requirements" / "connection.yaml"
STATUSES = {"planned", "current", "done"}
RID = re.compile(r"^R-\d{2}$")
RID_TOKEN = re.compile(r"R-[A-Za-z0-9_-]*")
PY_MARK = re.compile(r"mark\.req\(([^)]*)\)", re.DOTALL)
TS_REQ = re.compile(r"//\s*req:(.*)$")


class SpecError(Exception):
    """The requirements yaml is invalid."""


@dataclass(frozen=True)
class Requirement:
    rid: str
    title: str
    phases: tuple[str, ...]
    built: bool


def load_requirements(path: Path) -> tuple[dict[str, str], dict[str, Requirement]]:
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise SpecError(f"{path}: invalid yaml: {exc}") from exc
    if not isinstance(data, dict):
        raise SpecError(f"{path}: top level must be a mapping")
    raw_phases = data.get("phases") or {}
    phases: dict[str, str] = {}
    for pid, info in raw_phases.items():
        status = info.get("status") if isinstance(info, dict) else None
        if status not in STATUSES:
            raise SpecError(f"{pid}: status {status!r} not in {sorted(STATUSES)}")
        phases[str(pid)] = status
    current = [p for p, s in phases.items() if s == "current"]
    if len(current) > 1:
        raise SpecError(f"more than one current phase: {', '.join(current)}")
    reqs: dict[str, Requirement] = {}
    for rid, info in (data.get("requirements") or {}).items():
        rid = str(rid)
        if not RID.match(rid):
            raise SpecError(f"{rid}: not a valid R-ID (R-nn)")
        info = info or {}
        rphases = tuple(info.get("phases") or ())
        if not rphases:
            raise SpecError(f"{rid}: no phases")
        for p in rphases:
            if p not in phases:
                raise SpecError(f"{rid}: unknown phase {p}")
        reqs[rid] = Requirement(rid, str(info.get("title", "")), rphases, bool(info.get("built", False)))
    return phases, reqs


def collect_tags(repo: Path) -> dict[str, list[str]]:
    tags: dict[str, list[str]] = {}

    def add(token: str, where: str) -> None:
        tags.setdefault(token, []).append(where)

    for f in sorted((repo / "backend" / "tests").rglob("*.py")):
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f.relative_to(repo).as_posix()
        for m in PY_MARK.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            for tok in RID_TOKEN.findall(m.group(1)):
                add(tok, f"{rel}:{line}")
    fe = repo / "frontend"
    if fe.is_dir():
        files = [p for pat in ("*.test.ts", "*.test.tsx") for p in fe.rglob(pat)]
        for f in sorted(files):
            parts = f.relative_to(fe).parts
            if "node_modules" in parts or ".next" in parts:
                continue
            rel = f.relative_to(repo).as_posix()
            for n, line in enumerate(f.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                m = TS_REQ.search(line)
                if m:
                    for tok in RID_TOKEN.findall(m.group(1)):
                        add(tok, f"{rel}:{n}")
    return tags


def find_problems(
    phases: dict[str, str],
    reqs: dict[str, Requirement],
    tags: dict[str, list[str]],
    gate: str | None = None,
) -> list[str]:
    problems: list[str] = []
    for tok, places in sorted(tags.items()):
        if not RID.match(tok):
            problems.append(f"{tok}: malformed R-ID tagged in {places[0]}")
        elif tok not in reqs:
            problems.append(f"{tok}: tagged in {places[0]} but not in docs/requirements/connection.yaml")
    if gate is not None and gate not in phases:
        problems.append(f"{gate}: unknown phase for --gate")
    for rid, r in sorted(reqs.items()):
        if tags.get(rid):
            continue
        if r.built:
            problems.append(f"{rid}: built but no tagged test")
        elif any(phases[p] == "done" for p in r.phases):
            problems.append(f"{rid}: phase done but no tagged test")
        elif gate is not None and gate in r.phases:
            problems.append(f"{rid}: required by gate {gate} but no tagged test")
    return problems


def render_report(reqs: dict[str, Requirement], tags: dict[str, list[str]], phase: str) -> str:
    rows = ["| R-ID | Title | Built | Tests |", "|---|---|---|---|"]
    for rid, r in sorted(reqs.items()):
        if phase in r.phases:
            tests = ", ".join(tags.get(rid, [])) or "none"
            rows.append(f"| {rid} | {r.title} | {'yes' if r.built else 'no'} | {tests} |")
    return "\n".join(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gate", metavar="P<N>")
    ap.add_argument("--report", metavar="P<N>")
    args = ap.parse_args(argv)
    try:
        phases, reqs = load_requirements(YAML_PATH)
    except SpecError as exc:
        print(f"SpecError: {exc}")
        return 1
    tags = collect_tags(REPO)
    if args.report:
        print(render_report(reqs, tags, args.report))
        return 0
    problems = find_problems(phases, reqs, tags, args.gate)
    for p in problems:
        print(p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
