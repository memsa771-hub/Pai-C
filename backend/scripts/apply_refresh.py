"""Apply a reviewed rules and calendar refresh proposal to the policy files.

Run from backend/: python -m scripts.apply_refresh PROPOSAL.json [--only PATH ...]
Each diff names "<policy file>:<pointer>" (BETA_CONVERSATION_SPEC 3.3). A diff
is applied only while the file still holds its "old" value; a changed value is
reported as stale and left alone. The admission-rules and calendar validation
tests (rules_refresh.json validation_tests) then run; if they fail, every file
is put back exactly as it was.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
POLICY_DIR = BACKEND / "app" / "pai_c" / "policy"


def _settings(policy_dir: Path) -> dict:
    return json.loads((policy_dir / "rules_refresh.json").read_text(encoding="utf-8"))


def run_validation(tests: list[str]) -> bool:
    """The validation tests in a fresh interpreter, so they read the files as written."""
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]
    return subprocess.run(command, cwd=BACKEND).returncode == 0


def _parent(data, pointer: str):
    parts = pointer.split("/")
    node = data
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node, (int(parts[-1]) if isinstance(node, list) else parts[-1])


def _write(path: Path, data, original: bytes) -> None:
    """Same indent as the policy files; keep the file's line endings and final newline."""
    text = json.dumps(data, indent=1, ensure_ascii=False)
    if original.endswith(b"\n"):
        text += "\n"
    if b"\r\n" in original:
        text = text.replace("\n", "\r\n")
    path.write_bytes(text.encode("utf-8"))


def apply_proposal(proposal_path: Path, only: list[str] | None = None, *,
                   policy_dir: Path = POLICY_DIR, validate=None) -> dict:
    """Apply the proposal's diffs (or only the named paths), validate, and
    revert on failure. Returns {"applied", "stale", "valid"}."""
    proposal = json.loads(Path(proposal_path).read_text(encoding="utf-8"))
    diffs = [diff for diff in proposal.get("diffs", []) if not only or diff["path"] in only]
    originals: dict[str, bytes] = {}
    loaded: dict[str, object] = {}
    applied, stale = [], []
    for diff in diffs:
        name, pointer = diff["path"].split(":", 1)
        file = policy_dir / name
        if name not in loaded:
            originals[name] = file.read_bytes()
            loaded[name] = json.loads(originals[name].decode("utf-8"))
        try:
            parent, key = _parent(loaded[name], pointer)
            current = parent[key]
        except (KeyError, IndexError, ValueError, TypeError):
            stale.append(diff["path"])
            continue
        if current != diff["old"]:
            stale.append(diff["path"])
            continue
        parent[key] = diff["new"]
        applied.append(diff["path"])
    if not applied:
        return {"applied": [], "stale": stale, "valid": True}
    changed = {path.split(":", 1)[0] for path in applied}
    for name in changed:
        _write(policy_dir / name, loaded[name], originals[name])
    validate = validate or (lambda: run_validation(_settings(policy_dir)["validation_tests"]))
    if not validate():
        for name in changed:
            (policy_dir / name).write_bytes(originals[name])
        return {"applied": [], "stale": stale, "valid": False, "reverted": applied}
    return {"applied": applied, "stale": stale, "valid": True}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--only", action="append", default=None, metavar="PATH",
                        help="apply only this diff path (repeatable)")
    args = parser.parse_args(argv)
    result = apply_proposal(args.proposal, args.only)
    print(f"applied: {len(result['applied'])}  stale: {len(result['stale'])}  valid: {result['valid']}")
    for path in result["stale"]:
        print(f"stale (value changed since the proposal): {path}")
    if not result["valid"]:
        print("validation failed; the policy files were restored")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
