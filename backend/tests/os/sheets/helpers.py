"""Fictional batches for the P2-T6 tests: invented institutions on `.test` domains (P2 spec §5)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.os.knowledge.programmes import ProgrammeStore
from app.os.knowledge.sheets.importer import ImportDeps
from app.os.knowledge.sheets.template import write_workbook
from app.os.knowledge.store import SqlKnowledge
from app.os.registry.store import RegistryStore
from tests.os.registry.helpers import AT, LIST_URL, olist

C1 = "Claude – check 1"
C2 = "Claude – check 2 (independent)"
COUNTRY = "PK"  # the key of regions.yaml; the code under test names no country
NOTICE = "https://admissions.alpha.test/notice"


@dataclass
class Page:
    text: str = ""
    blocked: str | None = None


class FakeFetcher:
    def __init__(self, pages: dict[str, Page] | None = None):
        self.pages, self.calls = pages or {}, []

    def fetch(self, url, own_domains, shared_domains, scope=None):
        self.calls.append((url, scope))
        return self.pages.get(url, Page(blocked="not_official"))


class FakeDisputes:
    def __init__(self):
        self.items = []

    def open_item(self, kind, *, dedupe_key, fact_id=None, **kw):
        if any(i["dedupe_key"] == dedupe_key for i in self.items):
            return 0, False
        self.items.append({"kind": kind, "dedupe_key": dedupe_key, "fact_id": fact_id, **kw})
        return len(self.items), True


def checks(c1="correct", c2="yes", n1=C1, n2=C2) -> dict:
    return {"checker1_result": c1, "checker1_name": n1 if c1 else None, "checker2_approved": c2,
            "checker2_name": n2 if c2 else None}


def inst(n, *, ctype="private_medical_college", region="Punjab", status="found", chk=None, **kw) -> dict:
    row = {"inst_id": f"T-INST-{n:03d}", "type": ctype, "name": f"Test College {n}", "region": region,
           "official_url": f"https://college{n}.alpha.test/", "in_scope": "yes", "source_url": LIST_URL,
           "source_quote": f"Test College {n}", "read_method": "fetch", "retrieved": "2026-11-03",
           "claude_status": status}
    row.update(checks() if chk is None else chk)
    row.update(kw)
    return row


def fact(n, entity, *, field_="deadline_close", value="2027-07-15", intake="Fall 2027", status="found", chk=None,
         **kw) -> dict:
    row = {"fact_id": f"T-F-{n:03d}", "entity_id": entity, "field": field_, "value": value, "unit": "date",
           "intake": intake, "high_stakes": "Y", "source_url": NOTICE, "source_type": "html",
           "quote_verbatim": f"Last date {value}", "language": "en", "read_method": "fetch",
           "retrieved": "2026-11-03", "claude_status": status}
    row.update(checks() if chk is None else chk)
    row.update(kw)
    return row


def prog(n, inst_id, **kw) -> dict:
    row = {"programme_id": f"T-PRG-{n:03d}", "inst_id": inst_id, "programme": "Test Medicine", "level": "bachelor",
           "intake": "Session 2026-27", "seat_category": "open_merit", "seats": "100", "source_url": NOTICE,
           "quote_verbatim": "Open merit 100", "read_method": "fetch", "retrieved": "2026-11-03",
           "claude_status": "found"}
    row.update(checks())
    row.update(kw)
    return row


def workbook(tmp: Path, institutions=(), facts=(), programmes=(), name="batch.xlsx") -> Path:
    return write_workbook(tmp / name, {"Institutions": list(institutions), "Facts": list(facts),
                                       "Programmes": list(programmes)})


def deps(engine, **kw) -> ImportDeps:
    d = ImportDeps(engine, "pai", SqlKnowledge(engine, "pai"), RegistryStore(engine, "pai"),
                   ProgrammeStore(engine, "pai"))
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def load_list(engine, **kw) -> None:
    RegistryStore(engine, "pai").record(olist(**kw), cause="import")


__all__ = ["AT", "C1", "C2", "COUNTRY", "NOTICE", "datetime", "UTC", "field"]
