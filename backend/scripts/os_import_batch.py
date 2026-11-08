"""Validate, import and undo a returned research spreadsheet (P2 spec §4.6; master R-68). No SQL by hand.

    python -m scripts.os_import_batch template OUT.xlsx
    python -m scripts.os_import_batch validate FILE --country PK [--lists DIR] [--report OUT.csv]
    python -m scripts.os_import_batch import FILE --country PK --owner-accepted <decision ref> --actor NAME [--refetch]
    python -m scripts.os_import_batch import FILE --country PK --reviewers --batch-ref REF --actor NAME [--refetch]
    python -m scripts.os_import_batch undo IMPORT_ID --actor NAME
    python -m scripts.os_import_batch list

`validate` reads the file and plans every row; it touches no database (dry run). `--lists DIR` reads official-list
files (the H3 shape) to know the list URLs. `import --owner-accepted` is the separate mode for batches 1-5 (P2-D16a):
both checkers must be the two AI checks the owner accepted. `--reviewers` accepts only checkers that attested the batch.
`--refetch` re-fetches model- and OCR-read rows through the page gateway (R-68). Every import is logged; the report CSV
lists every row beside the file. Exit code 2 when refused.
"""

import argparse
import sys
from pathlib import Path

from app.os.knowledge.sheets.importer import (
    AlreadyImported,
    ImportDeps,
    build_context,
    plan_file,
    plan_hook,
    run_import,
    wire_other_tasks,
    write_report,
)
from app.os.knowledge.sheets.plan import OWNER_ACCEPTED, REVIEWERS, norm_url, summarise
from app.os.knowledge.sheets.reader import SheetError
from app.os.knowledge.sheets.template import write_template


def _list_urls(directory: Path | None, country: str) -> dict[str, str]:
    import yaml

    from app.os.registry.lists import parse_official_lists

    urls: dict[str, str] = {}
    for f in sorted(directory.glob("*.yaml")) if directory else []:
        for e in parse_official_lists(yaml.safe_load(f.read_text(encoding="utf-8")), country=country):
            urls[norm_url(e.source_url)] = e.entity_id
    return urls


def _print_counts(counts: dict, out) -> None:
    for sheet, c in counts.items():
        out(f"{sheet}: " + ", ".join(f"{k} {v}" for k, v in c.items()))


def main(argv: list[str] | None = None, deps: ImportDeps | None = None, out=print) -> int:
    parser = argparse.ArgumentParser(prog="scripts.os_import_batch", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("template").add_argument("out")
    for name in ("validate", "import"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--country", required=True, help="the key of regions.yaml, e.g. the ISO code of the country")
        p.add_argument("--family", default="", help="the batch's family (allow-list scope)")
        p.add_argument("--batch-ref", default=None)
        p.add_argument("--report", default=None)
    sub.choices["validate"].add_argument("--lists", default=None)
    sub.choices["validate"].add_argument("--decision-ref", default=None,
                                         help="the owner's decision reference: shows the plan with the spec §11.3 waiver")
    sub.choices["validate"].add_argument("--no-list-needed", action="store_true",
                                         help="what if every official list were loaded (dry run only)")
    imp = sub.choices["import"]
    mode = imp.add_mutually_exclusive_group(required=True)
    mode.add_argument("--owner-accepted", metavar="DECISION_REF")
    mode.add_argument("--reviewers", action="store_true")
    imp.add_argument("--actor", required=True)
    imp.add_argument("--refetch", action="store_true")
    imp.add_argument("--route-key", default="registry")
    undo = sub.add_parser("undo")
    undo.add_argument("import_id", type=int)
    undo.add_argument("--actor", required=True)
    sub.add_parser("list")
    args = parser.parse_args(argv)
    try:
        if args.cmd == "template":
            out(f"wrote {write_template(Path(args.out))}")
            return 0
        if args.cmd == "validate":
            ctx = build_context(None, country=args.country, mode=OWNER_ACCEPTED, batch_ref=args.batch_ref or "",
                                family=args.family, decision_ref=args.decision_ref, list_urls=_list_urls(Path(args.lists) if args.lists else None,
                                                                         args.country),
                                require_list=not args.no_list_needed)
            _, results = plan_file(Path(args.file), ctx)
            if args.report:
                write_report(results, Path(args.report))
            _print_counts(summarise(results), out)
            return 0
        if deps is None:
            from app.os.db import make_engine
            from app.os.knowledge.programmes import ProgrammeStore
            from app.os.knowledge.research.pages import PageGateway
            from app.os.knowledge.store import SqlKnowledge
            from app.os.registry.store import RegistryStore
            from app.os.settings import load_settings

            settings = load_settings()
            engine, tenant = make_engine(settings), settings.tenant_id
            deps = ImportDeps(engine, tenant, SqlKnowledge(engine, tenant), RegistryStore(engine, tenant),
                              ProgrammeStore(engine, tenant),
                              fetcher=PageGateway(engine, tenant, settings) if getattr(args, "refetch", False) else None)
            deps = wire_other_tasks(deps)
            if args.cmd == "import":  # the plans that use an imported calendar date follow it (row 6.10)
                from app.os.api.services import make_services

                svc = make_services(settings)
                deps.on_fact_change = plan_hook(svc.plans, svc.kernel)
        if args.cmd == "import":
            res = run_import(Path(args.file), deps, mode=OWNER_ACCEPTED if args.owner_accepted else REVIEWERS,
                             actor=args.actor, country=args.country, decision_ref=args.owner_accepted,
                             batch_ref=args.batch_ref, family=args.family, route_key=args.route_key,
                             report_path=Path(args.report) if args.report else None)
            out(f"import {res.import_id} done; report {res.report_path}")
            _print_counts(res.counts, out)
        elif args.cmd == "undo":
            from app.os.knowledge.sheets.undo import undo_import

            r = undo_import(deps.engine, deps.tenant_id, args.import_id, actor=args.actor)
            out(f"undone: {r.facts} facts, {r.registry} registry rows, {r.programmes} programmes")
        else:
            from app.os.knowledge.sheets.importlog import ImportLog

            for rec in ImportLog(deps.engine, deps.tenant_id).list():
                out(f"{rec.id}\t{rec.status}\t{rec.mode}\t{rec.file_name}\t{rec.actor}\t{rec.started_at:%Y-%m-%d %H:%M}")
        return 0
    except (ValueError, SheetError, AlreadyImported, RuntimeError, KeyError) as e:
        out(f"refused: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
