"""Validate, import and undo a returned research spreadsheet (P2 spec §4.6; master R-68). No SQL by hand.

    python -m scripts.os_import_batch template OUT.xlsx
    python -m scripts.os_import_batch validate FILE --country PK [--lists DIR] [--allow-list DIR] [--report OUT.csv]
                                               [--aliases A.yaml] [--institutions-from OTHER.xlsx]...
    python -m scripts.os_import_batch import FILE --country PK --owner-accepted <decision ref> --actor NAME [--refetch]
    python -m scripts.os_import_batch import FILE --country PK --reviewers --batch-ref REF --actor NAME [--refetch]
    python -m scripts.os_import_batch undo IMPORT_ID --actor NAME
    python -m scripts.os_import_batch list

`validate` reads the file and plans every row; it touches no database (dry run). `--lists DIR` reads official-list
files (the H3 shape) to know the list URLs and regions: a row whose list serves another region is rejected as the import
would. Without the database `validate` cannot see the lists an entity already names (the import checks those too).
`--institutions-from OTHER` (dry run only, repeatable) plans OTHER the same
way and lets FILE's rows use the institutions OTHER would load, as if it were imported first. `import --owner-accepted` is the separate mode for batches 1-5 (P2-D16a):
both checkers must be the two AI checks the owner accepted. `--reviewers` accepts only checkers that attested the batch.
`--refetch` re-fetches model- and OCR-read rows through the page gateway (R-68). Every import is logged; the report CSV
lists every row beside the file. `--aliases FILE` (may repeat) gives alias files made for FILE (bound by its sha256): an
accepted alias makes an id of the file name an entity loaded under another id; the file itself stays unchanged. An
alias counts only when both its checkers attested the alias file's ref (`aliases-<sha256 of the alias file>`) in the
review queue; `validate --assume-aliases-attested` shows the plan as if they had.
The allow-list family of a row is the `family` of every official list its entity is on (`--lists` files for a dry run,
the registry for an import); `--family` is used only when none of them has one (P2-T19). `validate --allow-list DIR`
judges every source against the allow-list files in DIR as the import judges it against the same entries; without it the
dry run does not check the allow-list and says so. The files carry no database state: a domain marked suspect in the
database is refused by the import but not by the dry run.
Exit code 2 when refused.
"""

import argparse
import sys
from pathlib import Path

from app.os.knowledge.sheets.aliases import load_aliases
from app.os.knowledge.sheets.importer import (
    AlreadyImported,
    ImportDeps,
    build_context,
    official_by_host,
    plan_file,
    plan_hook,
    run_import,
    use_planned_institutions,
    wire_other_tasks,
    write_report,
)
from app.os.knowledge.sheets.plan import OWNER_ACCEPTED, REVIEWERS, norm_url, summarise
from app.os.knowledge.sheets.reader import SheetError
from app.os.knowledge.sheets.template import write_template


def _lists(directory: Path | None, country: str) -> tuple[dict[str, tuple[str, ...]], dict[str, str | None],
                                                          dict[str, str]]:
    """({list URL: the ids of every list at it}, {list id: region}, {list id: family}) of the official-list files in
    `directory`."""
    import yaml

    from app.os.registry.lists import parse_official_lists

    urls: dict[str, tuple[str, ...]] = {}
    regions: dict[str, str | None] = {}
    fams: dict[str, str] = {}
    for f in sorted(directory.glob("*.yaml")) if directory else []:
        for e in parse_official_lists(yaml.safe_load(f.read_text(encoding="utf-8")), country=country):
            u = norm_url(e.source_url)
            urls[u] = tuple(dict.fromkeys((*urls.get(u, ()), e.entity_id)))
            regions[e.entity_id] = e.region
            if e.attrs.get("family"):
                fams[e.entity_id] = str(e.attrs["family"])
    return urls, regions, fams


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
        p.add_argument("--family", default="",
                       help="the allow-list family of a row whose entity is on no official list with a family")
        p.add_argument("--batch-ref", default=None)
        p.add_argument("--report", default=None)
        p.add_argument("--aliases", action="append", default=[], metavar="FILE",
                       help="an alias file for this file (YAML; may repeat)")
    sub.choices["validate"].add_argument("--lists", default=None)
    sub.choices["validate"].add_argument("--allow-list", default=None, metavar="DIR",
                                         help="judge sources against the allow-list YAML files in DIR (no database)")
    sub.choices["validate"].add_argument("--decision-ref", default=None,
                                         help="the owner's decision reference: shows the plan with the spec §11.3 waiver")
    sub.choices["validate"].add_argument("--no-list-needed", action="store_true",
                                         help="what if every official list were loaded (dry run only)")
    sub.choices["validate"].add_argument("--assume-aliases-attested", action="store_true",
                                         help="what if both checkers of every alias had attested it (dry run only)")
    sub.choices["validate"].add_argument("--institutions-from", action="append", default=[], metavar="OTHER",
                                         help="resolve inst_ids against the institutions OTHER would load (dry run only)")
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
            urls, regions, fams = _lists(Path(args.lists) if args.lists else None, args.country)
            official, notes = None, []
            if args.allow_list:
                from app.os.knowledge.sources.allowlist import file_lookup, load_allowlist

                allow = load_allowlist(Path(args.allow_list))
                official = official_by_host(file_lookup(allow))
                notes.append(f"allow-list: checked against {len(allow.entries)} entries of {args.allow_list}, from "
                             "the files only: a domain marked suspect in the database is refused by the import but "
                             "not here")
                if not fams:
                    notes.append("allow-list: no list families (give --lists): every row is judged with --family "
                                 f"'{args.family}'")
            else:
                notes.append("allow-list: NOT checked (give --allow-list DIR); the import caps a row whose source is "
                             "not on the allow-list at unconfirmed (source_not_on_allow_list)")

            def context():
                c = build_context(None, country=args.country, mode=OWNER_ACCEPTED, batch_ref=args.batch_ref or "",
                                  family=args.family, decision_ref=args.decision_ref, list_urls=urls,
                                  list_regions=regions, list_families=fams,
                                  require_list=not args.no_list_needed)
                c.official = official
                return c

            ctx = context()
            for other in args.institutions_from:
                _, planned = plan_file(Path(other), context())
                use_planned_institutions(ctx, planned)
                out(f"institutions from {Path(other).name}: "
                    f"{sum(1 for r in planned if r.sheet == 'Institutions' and r.bucket in ('accepted', 'unconfirmed'))}")
            ctx.aliases = tuple(load_aliases(Path(a)) for a in args.aliases)
            if args.assume_aliases_attested:  # the dry run has no review queue; only alias refs are assumed
                ctx.attested = lambda name, ref: ref.startswith("aliases-")
            _, results = plan_file(Path(args.file), ctx)
            if args.report:
                write_report(results, Path(args.report))
            for note in notes:  # after the plan: a refused file still starts its output with "refused:"
                out(note)
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
            if args.cmd in ("import", "undo"):  # the plans that use an imported or withdrawn fact follow it (row 6.10)
                from app.os.api.services import make_services

                svc = make_services(settings)
                deps.on_fact_change = plan_hook(svc.plans, svc.kernel)
        if args.cmd == "import":
            res = run_import(Path(args.file), deps, mode=OWNER_ACCEPTED if args.owner_accepted else REVIEWERS,
                             actor=args.actor, country=args.country, decision_ref=args.owner_accepted,
                             batch_ref=args.batch_ref, family=args.family, route_key=args.route_key,
                             report_path=Path(args.report) if args.report else None,
                             aliases=[Path(a) for a in args.aliases])
            out(f"import {res.import_id} done; report {res.report_path}")
            _print_counts(res.counts, out)
        elif args.cmd == "undo":
            from app.os.knowledge.sheets.undo import undo_import

            r = undo_import(deps.engine, deps.tenant_id, args.import_id, actor=args.actor,
                            on_fact_change=deps.on_fact_change)
            out(f"undone: {r.facts} facts, {r.registry} registry rows, {r.programmes} programmes")
        else:
            from app.os.knowledge.sheets.importlog import ImportLog

            for rec in ImportLog(deps.engine, deps.tenant_id).list():
                out(f"{rec.id}\t{rec.status}\t{rec.mode}\t{rec.file_name}\t{rec.actor}\t{rec.started_at:%Y-%m-%d %H:%M}"
                    + (f"\taliases: {', '.join(a['alias_file'] for a in rec.aliases)}" if rec.aliases else ""))
        return 0
    except (ValueError, SheetError, AlreadyImported, RuntimeError, KeyError) as e:
        out(f"refused: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
