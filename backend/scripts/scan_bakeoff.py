"""Runs the ScanText bake-off on fictional scans built in memory (P2-D13). Run from backend/:

    python scripts/scan_bakeoff.py [--json out.json]

Engines that are not installed are listed as `not run`. Nothing is sent anywhere and nothing is paid."""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.os.knowledge.research.bakeoff import (
    run_bakeoff,
    summarise,
    winner,
)
from app.os.knowledge.research.scan import (
    DoclingScanText,
    TesseractScanText,
)
from tests.os.scan_fixtures import bakeoff_cases


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="write the scores here")
    args = ap.parse_args()
    adapters = [TesseractScanText(), DoclingScanText()]
    cases = bakeoff_cases()
    scores = run_bakeoff(adapters, cases)
    summary = summarise(scores)
    print(f"{len(cases)} fictional cases: {', '.join(c.name for c in cases)}")
    for a in adapters:
        s = summary[a.name]
        if not s["ran"]:
            print(f"{a.name:10} not run (not installed)")
        else:
            print(f"{a.name:10} ran {s['ran']}/{s['cases']}  quotes {s['quote_pass_rate']:.0%}  "
                  f"similarity {s['mean_similarity']:.2f}  {s['mean_seconds']:.1f}s  failures {s['failures']}")
    print("winner:", winner(summary) or "none (no engine ran every case and matched every quote)")
    if args.json:
        Path(args.json).write_text(json.dumps({"summary": summary, "scores": [asdict(s) for s in scores]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
