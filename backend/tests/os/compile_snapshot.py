"""P3-T1 byte-for-byte guard: every shipped and fixture playbook, compiled with synthetic inputs, as stable JSON.

The snapshot file (`golden/compile_snapshot.json`) was written by this module at the base commit 30d70d2b, before the
family schema existed. It was regenerated on 2026-11-15 at 74d4be51 (germany_master.v3 added by P2-T25, still without
the family schema); the P3-T1 head produces the same bytes (sha256 e44a4bae...). `test_p3t1_family.py` compiles again and compares the bytes. Regenerate only on purpose:
`python -m tests.os.compile_snapshot` (from backend/).
"""

import json
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from app.os.compiler import compile_plan, needed_fields
from app.os.contracts.route_contract import RouteContract
from app.os.contracts.route_contract_v2 import RouteContractV2
from app.os.knowledge import Fact
from app.os.playbooks import PLAYBOOK_DIR, load_playbook
from app.os.requests.state import StudentState

HERE = Path(__file__).parent
SNAPSHOT = HERE / "golden" / "compile_snapshot.json"
FIXTURES = HERE / "playbooks"
TODAY = date(2027, 2, 1)
CHECKED = datetime(2026, 10, 17, tzinfo=timezone.utc)
REFS = ("prog-a.test", "prog-b.test")


def playbook_files() -> list[Path]:
    """Germany (the shipped playbooks) and every fixture playbook under tests/os/playbooks (not the pages sidecars)."""
    shipped = sorted(PLAYBOOK_DIR.glob("*.yaml"))
    fixtures = sorted(p for p in FIXTURES.rglob("*.yaml") if "pages" not in p.relative_to(FIXTURES).parts)
    return shipped + fixtures


def _contract(book):
    level = book.route.level
    data = {"source": "self_serve", "external_ref": "snap-1", "student_ref": "snap-student",
            "origin_country": book.route.origin, "destination_country": book.route.destination, "level": level,
            "target_intake": {"term": (book.intake_terms or ["winter"])[0], "year": 2027},
            "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(REFS)]}
    if level == "intermediate":
        return RouteContractV2.model_validate({**data, "contract_version": "2"})
    return RouteContract.model_validate({**data, "contract_version": "1"})


def _fact(value) -> Fact:
    return Fact(value=value, quote="q", url="https://facts.test/p", checked_at=CHECKED, intake_year=2027,
                status="confirmed")


def _facts(book):
    """Every field the playbook reads, as a confirmed date fact, so anchors and conditions are exercised too."""
    route_fields, programme_fields = needed_fields(book)
    route = {name: _fact({"date": "2027-06-30"}) for name in sorted(route_fields)}
    programme = {(ref, name): _fact({"date": f"2027-0{7 + i}-15"})
                 for i, ref in enumerate(REFS) for name in sorted(programme_fields)}
    return route, programme


def _draft_json(draft) -> dict:
    return json.loads(json.dumps(asdict(draft), default=str, sort_keys=True))


def compile_all() -> dict:
    out: dict[str, dict] = {}
    for path in playbook_files():
        book = load_playbook(path)
        shipped = path.is_relative_to(PLAYBOOK_DIR)
        name = f"{'app' if shipped else 'tests'}:{path.relative_to(PLAYBOOK_DIR if shipped else FIXTURES).as_posix()}"
        contract = _contract(book)
        route, programme = _facts(book)
        out[name] = {
            "no_facts": _draft_json(compile_plan(contract, book, {}, {}, TODAY)),
            "date_facts": _draft_json(compile_plan(contract, book, route, programme, TODAY)),
            "empty_student": _draft_json(compile_plan(contract, book, route, programme, TODAY,
                                                      student=StudentState())),
        }
    return out


def render() -> str:
    return json.dumps(compile_all(), indent=1, sort_keys=True, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    SNAPSHOT.write_text(render(), encoding="utf-8", newline="\n")
    print(f"wrote {SNAPSHOT}")
