"""Set `family` on programmes imported before the importer wrote it (P3-T2, ADR-001 D4). No SQL by hand.

    python -m scripts.os_programme_family_backfill --family CODE --import ID [--import ID ...] [--apply] [--actor NAME]
    python -m scripts.os_programme_family_backfill --undo family-backfill-<time> [--actor NAME]

The importer's rule: the programmes an import placed belong to the family its run was given (`--family`), unless their
institution is on an official list of another family (left alone: `family_conflicts_with_list`). The imports did not
record their `--family`, so name it with the imports it applies to (`scripts.os_import_batch list` shows them).
A programme no named import placed is never touched, and one that already has another family is reported, not changed.
A dry run by default; `--apply` writes each change as a registry revision with the run's cause_ref, printed at the end.
`--undo REF` restores every programme of that run; it refuses, and changes nothing, if one changed after the run.
Needs OS_DATABASE_URL (or DATABASE_URL) and optionally OS_TENANT_ID. Exit code 2 when refused.
"""

import argparse
import sys

from app.os.knowledge.family_backfill import BackfillRefused, run_backfill, undo_backfill


def main(argv: list[str] | None = None, engine=None, tenant_id: str | None = None, out=print) -> int:
    p = argparse.ArgumentParser(prog="scripts.os_programme_family_backfill", description=__doc__.splitlines()[0])
    p.add_argument("--family", help="the family code the imports' run had, e.g. as in the official lists")
    p.add_argument("--import", dest="imports", type=int, action="append", default=[], metavar="ID")
    p.add_argument("--apply", action="store_true", help="write the changes (default: a dry run)")
    p.add_argument("--undo", metavar="CAUSE_REF", help="undo an applied run")
    p.add_argument("--actor", default="os.family_backfill")
    args = p.parse_args(argv)
    if engine is None:
        from app.os.db import make_engine
        from app.os.settings import load_settings

        settings = load_settings()
        engine, tenant_id = make_engine(settings), settings.tenant_id
    try:
        if args.undo:
            if args.family or args.imports or args.apply:
                raise BackfillRefused("--undo takes no --family, --import or --apply")
            res = undo_backfill(engine, tenant_id, args.undo, actor=args.actor)
            for ref in res.restored:
                out(f"restored {ref}")
            out(f"undone {res.cause_ref}: {len(res.restored)} programme(s)")
            return 0
        res = run_backfill(engine, tenant_id, family=args.family or "", imports=args.imports, apply=args.apply,
                           actor=args.actor)
        for c in res.changes:
            out(f"{'set' if res.applied else 'would set'} {c.ref}: family {c.before or '(none)'} -> {c.after} "
                f"({c.institution_id})")
        for s in res.skipped:
            out(f"left alone ({s.reason}): {s.ref}" + (f" - {s.detail}" if s.detail else ""))
        out(f"{len(res.changes)} change(s), {len(res.skipped)} left alone, {res.unchanged} already {res.family}; "
            + (f"applied as {res.cause_ref} (undo: --undo {res.cause_ref})" if res.applied
               else "nothing applied" if args.apply else "dry run: nothing written (--apply writes)"))
        return 0
    except BackfillRefused as e:
        out(f"refused: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
