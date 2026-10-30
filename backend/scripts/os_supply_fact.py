"""Admin fallback for a programme fact research cannot find, e.g. `semester_start` (Slice 9b entry condition 2).

    python -m scripts.os_supply_fact list
    python -m scripts.os_supply_fact show --programme REF --intake 2027 [--field semester_start]
    python -m scripts.os_supply_fact supply --programme REF --intake 2027 --date 2027-10-11 \
        --url URL --quote "TEXT COPIED FROM THE PAGE" [--status confirmed] [--tz Area/City] [--note TEXT]
    python -m scripts.os_supply_fact confirm --fact-id ID --date 2027-10-11 --url URL --quote "TEXT" [...]

`supply` and `confirm` run the same code as POST /v1/os/facts and POST /v1/os/facts/{id}/confirm (the request
models, `supply_fact` / `confirm_fact`), so they validate exactly as the API does, complete the waiting confirm
tasks and revise the plans. No new HTTP route. The date's time zone defaults to the route playbook's.
Needs OS_DATABASE_URL (or DATABASE_URL) and optionally OS_TENANT_ID. Exit code 2 when the input is refused.
See docs/os/runbooks/semester-start.md.
"""

import argparse
import json
import sys

from pydantic import ValidationError
from sqlalchemy import select

from app.os import models
from app.os.api.queries import open_facts
from app.os.api.schemas import ConfirmIn, SupplyIn
from app.os.api.self_serve import newest_books
from app.os.knowledge.programmes import ProgrammeStore
from app.os.workers import confirm_fact, open_confirm_tasks, supply_fact

F = models.knowledge_facts


class Refused(Exception):
    """Input the API would refuse (its 404 or 422)."""


def _programme(svc, ref: str):
    prog = ProgrammeStore(svc.engine, svc.settings.tenant_id).get(ref)
    if prog is None:
        raise Refused(f"unknown programme '{ref}'")
    return prog


def _value(svc, args, ref: str) -> dict:
    tz = args.tz or newest_books(svc.plans)[_programme(svc, ref).route_key].default_timezone
    return {"date": args.date, "tz": tz}


def _fact_body(args) -> dict:
    return {"quote": args.quote, "url": args.url, "status": args.status, "conflict_note": args.note}


def cmd_list(svc, args) -> int:
    tenant = svc.settings.tenant_id
    items = open_facts(svc.engine, tenant, open_confirm_tasks(svc.engine, tenant))
    if not items:
        print("no open confirm tasks")
    for i in items:
        fact = i["fact"]
        state = "no fact yet" if fact is None else (
            f"fact {fact['fact_id']} {fact['status']} value={json.dumps(fact['value'])} source={fact['source']}")
        run = i["last_research_run"]
        print(f"task {i['task_id']} plan {i['plan_id']} {i['ref']} {i['field']} intake {i['intake_year']}: {state}"
              + (f"; last research run {run['id']} {run['status']}" if run else "; never researched"))
    return 0


def cmd_show(svc, args) -> int:
    with svc.engine.connect() as conn:
        row = conn.execute(select(F).where(F.c.tenant_id == svc.settings.tenant_id, F.c.scope == "programme",
                                           F.c.ref == args.programme, F.c.field == args.field,
                                           F.c.intake_year == args.intake)).first()
    if row is None:
        print(f"{args.programme} {args.field} {args.intake}: no fact (research found nothing yet)")
        return 0
    print(f"fact {row.id}: {row.status} value={json.dumps(row.value)} source={row.source} "
          f"checked {row.checked_at:%Y-%m-%d}")
    print(f"  url: {row.url}\n  quote: {json.dumps(row.quote)}")
    if row.conflict_note:
        print(f"  note: {row.conflict_note}")
    for e in row.evidence or []:
        print(f"  reading {e.get('reading')}: value={json.dumps(e.get('value'))} cycle={e.get('cycle')} "
              f"reasons={e.get('reasons')}\n    url: {e.get('url')}\n    quote: {json.dumps(e.get('quote'))}")
    return 0


def cmd_supply(svc, args) -> int:
    body = SupplyIn.model_validate({**_fact_body(args), "scope": "programme", "ref": args.programme,
                                    "field": args.field, "intake_year": args.intake,
                                    "value": _value(svc, args, args.programme)})
    revised = supply_fact(svc.plans, svc.knowledge, svc.kernel, **body.model_dump())
    print(f"stored {args.programme} {args.field} {args.intake} ({body.status}); revised plans: {revised}")
    return 0


def cmd_confirm(svc, args) -> int:
    try:
        _, ref, field, _ = svc.knowledge.get(args.fact_id)
    except KeyError:
        raise Refused("fact not found") from None
    body = ConfirmIn.model_validate({**_fact_body(args), "value": _value(svc, args, ref)})
    revised = confirm_fact(svc.plans, svc.knowledge, svc.kernel, args.fact_id, **body.model_dump())
    print(f"confirmed fact {args.fact_id} ({ref} {field}, {body.status}); revised plans: {revised}")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="scripts.os_supply_fact", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="open confirm tasks, with their facts and last research run")
    show = sub.add_parser("show", help="the stored fact and every research reading's evidence")
    for p in (show, sub.add_parser("supply", help="add or replace the fact (POST /v1/os/facts)")):
        p.add_argument("--programme", required=True)
        p.add_argument("--intake", required=True, type=int)
        p.add_argument("--field", default="semester_start")
    confirm = sub.add_parser("confirm", help="correct or confirm a fact by id (POST /v1/os/facts/{id}/confirm)")
    confirm.add_argument("--fact-id", required=True, type=int)
    for name in ("supply", "confirm"):
        p = sub.choices[name]
        p.add_argument("--date", required=True, help="YYYY-MM-DD, the first day of lectures")
        p.add_argument("--url", required=True, help="the official page that states it")
        p.add_argument("--quote", required=True, help="the words on that page, copied")
        p.add_argument("--status", default="confirmed")
        p.add_argument("--tz", help="time zone of the date (default: the route playbook's)")
        p.add_argument("--note", help="conflict note shown with the fact")
    return parser


COMMANDS = {"list": cmd_list, "show": cmd_show, "supply": cmd_supply, "confirm": cmd_confirm}


def main(argv: list[str] | None = None, services=None) -> int:
    args = _parser().parse_args(argv)
    svc = services
    if svc is None:
        from app.os.api.services import make_services
        from app.os.settings import load_settings

        svc = make_services(load_settings())
    try:
        return COMMANDS[args.cmd](svc, args)
    except (Refused, ValidationError, ValueError) as e:  # what the API answers with 404 or 422
        print(f"refused: {e}", file=sys.stderr)
        return 2
    finally:
        if services is None:
            svc.engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
