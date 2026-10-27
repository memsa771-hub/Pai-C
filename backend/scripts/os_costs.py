"""AI cost per student between two dates (Slice 9 spec §3.4). Read only; prints student refs and money, nothing else.

    python -m scripts.os_costs --from YYYY-MM-DD --to YYYY-MM-DD

Needs OS_DATABASE_URL (or DATABASE_URL) and optionally OS_TENANT_ID. Both dates are included (UTC calendar days).
"""

import argparse
import sys
from datetime import date

from app.os.costs import CostReport, cost_report
from app.os.db import make_engine
from app.os.settings import load_settings


def render(report: CostReport) -> str:
    lines = [f"AI cost {report.start} to {report.end} (USD)"]
    for s in report.students:
        lines.append(f"{s.student_ref}  documents={s.documents_usd}  statements={s.statements_usd}  "
                     f"replan={s.replan_usd}  total={s.total_usd}  {s.flag}")
    if not report.students:
        lines.append("no student costs")
    lines.append(f"research (shared) = {report.research_usd}")
    lines.append(f"unlinked = {report.unlinked_rows} rows, {report.unlinked_usd}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scripts.os_costs", description=__doc__.splitlines()[0])
    parser.add_argument("--from", dest="start", required=True, type=date.fromisoformat, metavar="YYYY-MM-DD")
    parser.add_argument("--to", dest="end", required=True, type=date.fromisoformat, metavar="YYYY-MM-DD")
    args = parser.parse_args(argv)
    if args.end < args.start:
        parser.error("--to is before --from")
    settings = load_settings()
    engine = make_engine(settings)
    try:
        print(render(cost_report(engine, settings.tenant_id, args.start, args.end)))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
