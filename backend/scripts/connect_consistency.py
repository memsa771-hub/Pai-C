"""Owner CLI for the Counsellor/PAI OS consistency check (P1-T10, R-05): `python scripts/connect_consistency.py run|status`.
`run` runs the check now (mode nightly) and opens a case per mismatch; `status` lists the open case counts per rule.
It prints rule numbers and counts only, never a student reference or a value.
Exit codes: 0 clean, 1 findings, 2 usage, 3 PAI OS not mounted or the check is off."""

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

COMMANDS = ("run", "status")


def _print_counts(counts: dict) -> None:
    for rule in range(1, 9):
        print(f"rule {rule}: {counts.get(rule, 0)}")


def main(argv: list[str], db=None) -> int:
    """`db`: a Counsellor session (tests pass one, and have configured the OS ports themselves)."""
    if len(argv) != 1 or argv[0] not in COMMANDS:
        print("usage: connect_consistency.py run|status", file=sys.stderr)
        return 2
    own = db is None
    if own:
        from app import main as _app  # noqa: F401  (mounts PAI OS and configures its ports, as the running backend does)
        from app.database import SessionLocal

        db = SessionLocal()
    try:
        from app import pai_os_bridge as bridge
        from app.os import ports
        from app.os.ports import consistency as port

        try:
            ports.services()
        except ports.OsUnavailable:
            print("PAI OS is not mounted")
            return 3
        if argv[0] == "run":
            got = bridge.consistency_run(db, mode="nightly", open_cases=True)
            if "skipped" in got:
                print("consistency check: off (the counsellor module or CONNECT_HANDOFF is off)")
                return 3
            print(f"students: {got['students']}")
            _print_counts(got["findings"])
            print(f"opened: {got['opened']}")
            print(f"touched: {got['touched']}")
            print(f"errors: {got['errors']}")
            return 1 if got["findings"] or got["errors"] else 0
        open_cases = port.cases("open")
        per_rule: dict[int, int] = {}
        for c in open_cases:
            per_rule[c.rule] = per_rule.get(c.rule, 0) + 1
        _print_counts(per_rule)
        print(f"open cases: {len(open_cases)}")
        return 0
    finally:
        if own:
            db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
