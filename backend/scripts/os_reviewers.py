"""Add, list, disable and re-key reviewers of the review queue (P2-D15). No SQL by hand.

    python -m scripts.os_reviewers add --ref amina --name "Amina" --role checker [--kind person]
    python -m scripts.os_reviewers add --ref ai_check_1 --name "AI check 1" --role checker --kind ai
    python -m scripts.os_reviewers list
    python -m scripts.os_reviewers disable --ref amina        (their past checks stay)
    python -m scripts.os_reviewers enable --ref amina
    python -m scripts.os_reviewers rotate --ref amina         (a new token; the old one stops working)

Roles: checker (gives the `check` step), approver (the `approve` step), admin (either, and sees all reviews).
Kinds: person, ai. Which kinds count towards `verified` is the review policy file, not this script.
`add` and `rotate` print the token once. It is stored hashed and cannot be shown again; give it to the reviewer
over a private channel. Needs OS_DATABASE_URL (or DATABASE_URL) and optionally OS_TENANT_ID. Exit code 2 when refused.
"""

import argparse
import sys

from app.os.knowledge.review.reviewers import ReviewerError, ReviewerStore


def main(argv: list[str] | None = None, engine=None, tenant_id: str | None = None, out=print) -> int:
    parser = argparse.ArgumentParser(prog="scripts.os_reviewers", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add", help="a new reviewer; prints the token once")
    add.add_argument("--ref", required=True, help="the id used in checks and spreadsheets, e.g. amina")
    add.add_argument("--name", required=True)
    add.add_argument("--role", required=True, choices=("checker", "approver", "admin"))
    add.add_argument("--kind", default="person", choices=("person", "ai"))
    sub.add_parser("list", help="every reviewer, active or not")
    for name in ("disable", "enable", "rotate"):
        sub.add_parser(name).add_argument("--ref", required=True)
    args = parser.parse_args(argv)
    own = engine is None
    if own:
        from app.os.db import make_engine
        from app.os.settings import load_settings

        settings = load_settings()
        engine, tenant_id = make_engine(settings), settings.tenant_id
    store = ReviewerStore(engine, tenant_id or "pai")
    try:
        if args.cmd == "add":
            r, token = store.add(args.ref, args.name, args.role, args.kind)
            out(f"added {r.ref} ({r.role}, {r.kind}). Token (shown once): {token}")
        elif args.cmd == "list":
            for r in store.list():
                out(f"{r.ref}\t{r.display_name}\t{r.role}\t{r.kind}\t{'active' if r.active else 'disabled'}")
        elif args.cmd in ("disable", "enable"):
            if not store.set_active(args.ref, args.cmd == "enable"):
                raise ReviewerError(f"no reviewer '{args.ref}'")
            out(f"{args.cmd}d {args.ref}")
        else:
            token = store.rotate(args.ref)
            if token is None:
                raise ReviewerError(f"no reviewer '{args.ref}'")
            out(f"new token for {args.ref} (shown once): {token}")
    except ReviewerError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    finally:
        if own:
            engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
