"""Runs one rehearsal by hand (Slice 9a spec §2.4): the 12 students, or some, offline, optionally with worker kills.

    cd backend
    export OS_TEST_DATABASE_URL=postgresql://os_test:os_test@localhost:5432/os_test
    python -m tests.os.rehearsal.run --students all|S1,S3 [--kill] [--billed] --out ~/s9-rehearsal/<run>

It CLEANS the database it is given (every os_* table and the DBOS test schema), so point it only at os_test, and run
no pytest on that database at the same time. Offline AI by default. The failure log, the report and the worker logs go
to --out, which must be outside the repo (spec §2.5). Exit code: 0 when every student reached both end points and the
failure log is empty, 1 otherwise, 2 when it refused to start.

`--billed` (spec §2.7, S9-D9, plan ruling 5; only with the owners' OK) runs on real OpenAI: the API and the worker get
OS_MODEL_MODE=openai, OS_TENANT_ID=rehearsal-billed, OS_REHEARSAL=on and the four monthly caps. It refuses to start
unless OS_OPENAI_API_KEY is set and OS_RESEARCH_MONTHLY_USD, OS_DOCUMENTS_MONTHLY_USD, OS_STATEMENTS_MONTHLY_USD and
OS_REPLAN_MONTHLY_USD are all set and sum to at most $15 (unset caps would fall back to the much larger defaults). The
key is read from the environment only; it is never printed, logged or written to --out."""

import argparse
import logging
import math
import os
import sys
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path

from tests.os.rehearsal.driver import BACKEND, Rehearsal, load_students

REPO = BACKEND.parent
BILLED_TENANT = "rehearsal-billed"
BILLED_CAP_USD = 15.0
CAPS = ("OS_RESEARCH_MONTHLY_USD", "OS_DOCUMENTS_MONTHLY_USD", "OS_STATEMENTS_MONTHLY_USD", "OS_REPLAN_MONTHLY_USD")


class BilledRefused(Exception):
    """The billed run may not start: the reason names settings only, never the key's value."""


def billed_env(env: Mapping[str, str]) -> dict[str, str]:
    """The settings a billed run adds to the API's and the worker's environment, or BilledRefused. The key itself is
    checked for presence only and is not in the result: the worker takes it from the process environment."""
    if not (env.get("OS_OPENAI_API_KEY") or "").strip():
        raise BilledRefused("OS_OPENAI_API_KEY is not set (the owners set a budgeted PAI OS key)")
    caps: dict[str, str] = {}
    total = 0.0
    for name in CAPS:
        raw = (env.get(name) or "").strip()
        if not raw:
            raise BilledRefused(f"{name} is not set: all four caps must be set ({', '.join(CAPS)})")
        try:
            usd = float(raw)
        except ValueError:
            raise BilledRefused(f"{name} must be an amount in USD, got {raw!r}") from None
        if not math.isfinite(usd) or usd < 0:
            raise BilledRefused(f"{name} must be an amount in USD of 0 or more, got {raw!r}")
        caps[name] = raw
        total += usd
    if total > BILLED_CAP_USD + 1e-9:
        raise BilledRefused(f"the four caps sum to ${total:.2f}, over the ${BILLED_CAP_USD:.0f} hard cap (S9-D9)")
    return {"OS_MODEL_MODE": "openai", "OS_TENANT_ID": BILLED_TENANT, "OS_REHEARSAL": "on", **caps}


def parse(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--students", default="all", help="all, or a comma list such as S1,S3,S5")
    ap.add_argument("--kill", action="store_true", help="SIGKILL and restart the worker at random ticks (Linux)")
    ap.add_argument("--out", type=Path, default=None, help="default ~/s9-rehearsal/<UTC timestamp>")
    ap.add_argument("--seed", type=int, default=9, help="the random seed (days advanced, kill points)")
    ap.add_argument("--billed", action="store_true",
                    help="real OpenAI on tenant rehearsal-billed; needs the key and the four caps (sum <= 15 USD)")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse(argv)
    billed = None
    if args.billed:
        try:
            billed = billed_env(os.environ)
        except BilledRefused as err:
            print(f"--billed refused: {err}", file=sys.stderr)
            return 2
    every = list(load_students())
    names = every if args.students == "all" else [s.strip() for s in args.students.split(",") if s.strip()]
    default = Path("~/s9-rehearsal") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out = (args.out or default).expanduser().resolve()
    if out == REPO or REPO in out.parents:
        print(f"--out must be outside the repo ({REPO}): the failure log stays out of git", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    report = Rehearsal(names, out, kill=args.kill, seed=args.seed, billed=billed).run()
    print(report.markdown())
    print(f"report and failure log: {out}")
    done = all(set(r.reached) == {"ready_to_submit", "visa_ready"} for r in report.students.values())
    return 0 if done and not report.failures else 1


if __name__ == "__main__":
    sys.exit(main())
