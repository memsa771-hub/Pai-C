"""The yearly rollover and the term backfill (P2 spec §4.8; R-61, R-62, plan D-t1-1).

    python -m scripts.os_rollover --region CODE --family CODE --term TERM --year YYYY [--export slots.csv]
    python -m scripts.os_rollover --backfill-terms
    python -m scripts.os_rollover --list [--region CODE] [--family CODE]

The first form opens the intake from the previous one of the same region, family and term, adds the expected fact slots
(keys only, no values) and, with `--export`, writes the spreadsheet of slots with last year's values filled in and
labelled with their year. It is safe to run again. The second sets `intake_term` on facts from before P2 from each
route playbook's `intake_terms`; a route with none or several terms is listed and left alone. Both change only the
intake tables and the `intake_term` column; no fact value, status or URL is touched.
Needs OS_DATABASE_URL (or DATABASE_URL) and optionally OS_TENANT_ID. Exit code 2 when the input is refused.
"""

import argparse
import sys
from pathlib import Path

from app.os.intakes import IntakeError, IntakeStore, UnknownTerm
from app.os.intakes.rollover import (
    backfill_intake_terms,
    export_csv,
    rollover,
    slot_report,
)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="os_rollover", description=__doc__.split("\n")[0])
    p.add_argument("--region")
    p.add_argument("--family")
    p.add_argument("--term")
    p.add_argument("--year", type=int)
    p.add_argument("--export", type=Path, help="write the intake's slots as a CSV")
    p.add_argument("--backfill-terms", action="store_true", help="set intake_term on old facts from the playbooks")
    p.add_argument("--list", action="store_true", help="list the intakes")
    return p


def _backfill(svc) -> int:
    res = backfill_intake_terms(svc.engine, svc.settings.tenant_id, svc.plans.playbooks)
    print(f"{res.updated} fact(s) got an intake term")
    for s in res.skipped:
        print(f"  left alone ({s.reason}): {s.scope} {s.ref} {s.field} {s.intake_year}")
    return 0


def _list(svc, args) -> int:
    store = IntakeStore(svc.engine, svc.settings.tenant_id)
    for i in store.list_intakes(region=args.region, family=args.family):
        print(f"{i.region} {i.family} {i.term} {i.year} {i.state} id={i.id}")
    return 0


def _rollover(svc, args) -> int:
    missing = [n for n in ("region", "family", "term", "year") if getattr(args, n) in (None, "")]
    if missing:
        raise IntakeError("needs --" + ", --".join(missing))
    tenant = svc.settings.tenant_id
    extra = tuple(t for b in svc.plans.playbooks.values() for t in b.intake_terms)
    res = rollover(svc.engine, tenant, region=args.region, family=args.family, term=args.term, year=args.year,
                   extra_terms=extra)
    prev = f"{res.previous.year}" if res.previous else "none"
    print(f"intake {args.region} {args.family} {args.term} {args.year}: {res.intake.state}; "
          f"previous {prev}; {res.slots_added} slot(s) added, "
          f"{len(slot_report(svc.engine, tenant, res.intake.id))} in all")
    if args.export:
        print(f"{export_csv(svc.engine, tenant, res.intake.id, args.export)} row(s) written to {args.export}")
    return 0


def main(argv: list[str] | None = None, services=None) -> int:
    args = _parser().parse_args(argv)
    svc = services
    if svc is None:
        from app.os.api.services import make_services
        from app.os.settings import load_settings

        svc = make_services(load_settings())
    try:
        if args.backfill_terms:
            return _backfill(svc)
        if args.list:
            return _list(svc, args)
        return _rollover(svc, args)
    except (IntakeError, UnknownTerm) as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    finally:
        if services is None:
            svc.engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
