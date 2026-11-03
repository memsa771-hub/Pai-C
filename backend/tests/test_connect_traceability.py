"""Requirement traceability check (R-57, master spec section 13.1)."""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.req("R-57")

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "check_traceability.py"
MASTER = REPO_ROOT / "docs" / "superpowers" / "specs" / "2026-11-03-pai-connect-design.md"
YAML_FILE = REPO_ROOT / "docs" / "requirements" / "connection.yaml"

# Built in pieces so this file's own text holds no tag for the collector to read.
MARK = "pytest.mark." + "req"


def _load():
    spec = importlib.util.spec_from_file_location("check_traceability", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


ct = _load()


def _write_yaml(tmp_path, phases, reqs):
    lines = ["phases:"]
    lines += [f"  {p}: {{name: x, status: {s}}}" for p, s in phases.items()]
    lines.append("requirements:")
    for rid, (ps, built) in reqs.items():
        lines.append(f'  {rid}: {{title: "t", phases: [{", ".join(ps)}], built: {str(built).lower()}}}')
    path = tmp_path / "c.yaml"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ct.load_requirements(path)


def test_built_requirement_without_test_fails(tmp_path):
    phases, reqs = _write_yaml(tmp_path, {"P0": "current"}, {"R-01": (["P0"], True)})
    problems = ct.find_problems(phases, reqs, {})
    assert any(p.startswith("R-01") for p in problems)


def test_unbuilt_requirement_in_current_phase_is_allowed(tmp_path):
    phases, reqs = _write_yaml(tmp_path, {"P0": "current"}, {"R-47": (["P0"], False)})
    assert ct.find_problems(phases, reqs, {}) == []


def test_requirement_of_done_phase_without_test_fails(tmp_path):
    phases, reqs = _write_yaml(tmp_path, {"P0": "done"}, {"R-47": (["P0"], False)})
    assert any("R-47" in p for p in ct.find_problems(phases, reqs, {}))


def test_gate_requires_every_requirement_of_the_phase(tmp_path):
    phases, reqs = _write_yaml(tmp_path, {"P0": "current"}, {"R-47": (["P0"], False)})
    assert any("R-47" in p for p in ct.find_problems(phases, reqs, {}, gate="P0"))
    assert ct.find_problems(phases, reqs, {"R-47": ["x.py:1"]}, gate="P0") == []


def test_unknown_or_malformed_rid_is_reported(tmp_path):
    phases, reqs = _write_yaml(tmp_path, {"P0": "current"}, {"R-47": (["P0"], False)})
    problems = ct.find_problems(phases, reqs, {"R-99": ["a.py:3"], "R-7": ["b.py:4"]})
    assert any(p.startswith("R-99") for p in problems)
    assert any(p.startswith("R-7") for p in problems)


def test_invalid_yaml_raises(tmp_path):
    with pytest.raises(ct.SpecError):
        _write_yaml(tmp_path, {"P0": "current", "P1": "current"}, {"R-01": (["P0"], False)})
    with pytest.raises(ct.SpecError):
        _write_yaml(tmp_path, {"P0": "current"}, {"R-01": (["P9"], False)})
    with pytest.raises(ct.SpecError):
        _write_yaml(tmp_path, {"P0": "bogus"}, {"R-01": (["P0"], False)})
    with pytest.raises(ct.SpecError):
        _write_yaml(tmp_path, {"P0": "current"}, {"R-1": (["P0"], False)})
    with pytest.raises(ct.SpecError):
        _write_yaml(tmp_path, {"P0": "current"}, {"R-01": ([], False)})


def test_collect_tags_reads_decorators_pytestmark_and_frontend(tmp_path):
    tests = tmp_path / "backend" / "tests"
    tests.mkdir(parents=True)
    (tests / "test_a.py").write_text(
        f'import pytest\n\n@{MARK}("R-01", "R-02")\ndef test_x():\n    pass\n',
        encoding="utf-8",
    )
    (tests / "test_b.py").write_text(f'import pytest\n\npytestmark = {MARK}("R-03")\n', encoding="utf-8")
    fe = tmp_path / "frontend" / "components"
    fe.mkdir(parents=True)
    (fe / "a.test.tsx").write_text("// req: R-50, R-53\nit('x', () => {})\n", encoding="utf-8")
    nm = tmp_path / "frontend" / "node_modules" / "pkg"
    nm.mkdir(parents=True)
    (nm / "b.test.ts").write_text("// req: R-09\n", encoding="utf-8")
    tags = ct.collect_tags(tmp_path)
    assert set(tags) == {"R-01", "R-02", "R-03", "R-50", "R-53"}
    assert tags["R-03"][0].startswith("backend/tests/test_b.py:")


def _master_text():
    return MASTER.read_text(encoding="utf-8")


def test_yaml_lists_every_requirement_of_the_master_spec():
    master_ids = set(re.findall(r"^\| (R-\d{2}) \|", _master_text(), re.M))
    _, reqs = ct.load_requirements(YAML_FILE)
    assert master_ids == set(reqs) == {f"R-{i:02d}" for i in range(1, 82)}


def _expand(cell):
    cell = cell.split("using")[0]
    ids = set()
    for a, b in re.findall(r"R-(\d{2})\s*–\s*R-(\d{2})", cell):
        ids |= {f"R-{i:02d}" for i in range(int(a), int(b) + 1)}
    ids |= set(re.findall(r"R-\d{2}", cell))
    return ids


def test_yaml_phases_match_master_section_12():
    text = _master_text()
    section = text.split("## 12.", 1)[1].split("\n## 13.", 1)[0]
    from_spec = {}
    for row in section.splitlines():
        m = re.match(r"^\| \*\*(P\d)\b", row)
        if m:
            from_spec[m.group(1)] = _expand(row.split("|")[3])
    assert set(from_spec) == {f"P{i}" for i in range(7)}
    _, reqs = ct.load_requirements(YAML_FILE)
    for phase, ids in from_spec.items():
        for rid in ids:
            assert phase in reqs[rid].phases, f"{rid} missing {phase} in yaml"
    union = {(rid, p) for p, ids in from_spec.items() for rid in ids}
    for rid, r in reqs.items():
        for p in r.phases:
            assert (rid, p) in union, f"{rid} in {p} not in section 12"


def test_repository_passes_its_own_check(capsys):
    assert ct.main([]) == 0, capsys.readouterr().out
