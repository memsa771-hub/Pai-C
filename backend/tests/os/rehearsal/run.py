"""Runs one rehearsal by hand (Slice 9a spec §2.4): the 12 students, or some, offline, optionally with worker kills.

    cd backend
    export OS_TEST_DATABASE_URL=postgresql://os_test:os_test@localhost:5432/os_test
    python -m tests.os.rehearsal.run --students all|S1,S3 [--kill] --out ~/s9-rehearsal/<run>

It CLEANS the database it is given (every os_* table and the DBOS test schema), so point it only at os_test, and run
no pytest on that database at the same time. Offline AI only (the billed run is a later task). The failure log, the
report and the worker logs go to --out, which must be outside the repo (spec §2.5). Exit code: 0 when every student
reached both end points and the failure log is empty, 1 otherwise."""

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from tests.os.rehearsal.driver import BACKEND, Rehearsal, load_students

REPO = BACKEND.parent


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--students", default="all", help="all, or a comma list such as S1,S3,S5")
    ap.add_argument("--kill", action="store_true", help="SIGKILL and restart the worker at random ticks (Linux)")
    ap.add_argument("--out", type=Path, default=None, help="default ~/s9-rehearsal/<UTC timestamp>")
    ap.add_argument("--seed", type=int, default=9, help="the random seed (days advanced, kill points)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    every = list(load_students())
    names = every if args.students == "all" else [s.strip() for s in args.students.split(",") if s.strip()]
    default = Path("~/s9-rehearsal") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = (args.out or default).expanduser().resolve()
    if out == REPO or REPO in out.parents:
        print(f"--out must be outside the repo ({REPO}): the failure log stays out of git", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    report = Rehearsal(names, out, kill=args.kill, seed=args.seed).run()
    print(report.markdown())
    print(f"report and failure log: {out}")
    done = all(set(r.reached) == {"ready_to_submit", "visa_ready"} for r in report.students.values())
    return 0 if done and not report.failures else 1


if __name__ == "__main__":
    sys.exit(main())
