"""The Spike 1 rerun harness per region (P2-T12; P2 spec §9 item 7). It scores and plans; it never researches or calls a model.

    python -m scripts.os_spike1_rerun regions                       # the regions and which have an answer key
    python -m scripts.os_spike1_rerun plan  --region REGION [--cost-per-fact USD] [--spent USD] [--cap USD]
    python -m scripts.os_spike1_rerun score [--region REGION | --all] [--out FILE.json]

`score` compares the facts the system holds with each region's answer key (`tests/os/quality/<region>_answer_key.yaml`):
100% correct among verified facts, at least 95% among confirmed (master §12), on a sample of at least 5 institutions per
region. Exit code 0 when every scored region passes, 1 when one fails, 2 when the input is refused.
The billed research run that fills the facts is run by the owner's controller inside the cost cap; see the P2 handoff.
Needs OS_DATABASE_URL (or DATABASE_URL) and optionally OS_TENANT_ID."""

import argparse
import json
import sys
from pathlib import Path

from app.os.gate import spike1


def main(argv: list[str] | None = None, engine=None, tenant_id: str | None = None, key_dir: Path = spike1.KEY_DIR,
         out=print) -> int:
    parser = argparse.ArgumentParser(prog="scripts.os_spike1_rerun", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("regions")
    p = sub.add_parser("plan")
    p.add_argument("--region", required=True)
    p.add_argument("--cost-per-fact", type=float, default=0.034, help="USD per fact (the Slice 2 gate ran about $1 per 30 programmes)")
    p.add_argument("--spent", type=float, default=0.0, help="USD already spent in P2")
    p.add_argument("--cap", type=float, default=20.0)
    s = sub.add_parser("score")
    s.add_argument("--region")
    s.add_argument("--all", action="store_true")
    s.add_argument("--out")
    args = parser.parse_args(argv)
    try:
        found = spike1.keys_in(key_dir)
        if args.cmd == "regions":
            from app.os.knowledge.regions import countries, regions

            needed = sorted(r.code for c in countries() for r in regions(c))
            out(json.dumps(spike1.region_coverage({k: None for k in found}, needed), indent=1))
            return 0
        if args.cmd == "plan":
            if args.region not in found:
                raise spike1.KeyError_(f"no answer key for region '{args.region}'")
            out(json.dumps(spike1.plan(spike1.load_key(found[args.region]), cost_per_fact_usd=args.cost_per_fact,
                                       spent_usd=args.spent, cap_usd=args.cap), indent=1))
            return 0
        if not (args.region or args.all):
            raise spike1.KeyError_("give --region or --all")
        names = sorted(found) if args.all else [args.region]
        missing = [n for n in names if n not in found]
        if missing:
            raise spike1.KeyError_(f"no answer key for: {', '.join(missing)}")
        own = engine is None
        if own:
            from app.os.db import make_engine
            from app.os.settings import load_settings

            settings = load_settings()
            engine, tenant_id = make_engine(settings), settings.tenant_id
        try:
            scores = [spike1.score_key(engine, tenant_id or "pai", spike1.load_key(found[n])) for n in names]
        finally:
            if own:
                engine.dispose()
        report = {"regions": [sc.as_dict() for sc in scores], "passed": all(sc.passed for sc in scores)}
        if args.out:
            Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
        out(json.dumps(report, indent=1))
        return 0 if report["passed"] else 1
    except spike1.KeyError_ as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
