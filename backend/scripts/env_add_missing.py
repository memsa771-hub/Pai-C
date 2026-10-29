"""Append `NAME=` lines for settings missing from .env; never touch the rest.

Only the part of each line before `=` is looked at, so no existing value is
kept in memory, compared or printed. A default may follow a name (`NAME=value`)
only for non-secret settings; secrets are added empty for the founder to fill.

    python scripts/env_add_missing.py [--env PATH] [NAME[=value] ...]
"""
import argparse
import re
import sys
from pathlib import Path

ENV = Path(__file__).resolve().parents[2] / ".env"
# BETA_CONVERSATION_SPEC 1.3: names for the provider-per-role and monthly cap settings.
BETA_NAMES = [
    "ANTHROPIC_API_KEY",
    "PAI_COUNSELOR_PROVIDER=anthropic",
    "PAI_COUNSELOR_MODEL=claude-sonnet-5-5",
    "PAI_RESEARCHER_MODEL=gpt-5",
    "PAI_ANALYST_MODEL=gpt-5",
    "PAI_MIRROR_MODEL=gpt-5",
    "MEMORY_EMBEDDING_API_KEY",
    "PAI_SEMANTIC_RECALL_ENABLED=true",
    "PAI_MONTHLY_CAP_USD=100",
    "PAI_FOUNDER_EMAILS",
]
_NAME = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def present_names(path: Path) -> set[str]:
    if not path.exists():
        return set()
    names = set()
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            match = _NAME.match(line)
            if match:
                names.add(match.group(1))
    return names


def add_missing(path: Path, entries: list[str]) -> list[str]:
    """Append each entry whose name is not in the file; return the names appended."""
    present = present_names(path)
    lines, added = [], []
    for entry in entries:
        name, _, default = entry.partition("=")
        name = name.strip()
        if name and name not in present and name not in added:
            lines.append(f"{name}={default.strip()}")
            added.append(name)
    if lines:
        ends_open = False
        if path.exists() and path.stat().st_size > 0:
            with path.open("rb") as handle:  # only the last byte
                handle.seek(-1, 2)
                ends_open = handle.read(1) != b"\n"
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(("\n" if ends_open else "") + "\n".join(lines) + "\n")
    return added


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env", type=Path, default=ENV)
    parser.add_argument("entries", nargs="*")
    args = parser.parse_args(argv)
    added = add_missing(args.env, args.entries or BETA_NAMES)
    print("added: " + (", ".join(added) if added else "none"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
