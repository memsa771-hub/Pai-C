"""P2-T6: programme rows (and their legacy layouts) become programmes in the registry with their facts (P2 spec §4.1,
§4.6; master R-33, R-67)."""

import openpyxl
import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge.sheets.format import load_format
from app.os.knowledge.sheets.importer import run_import
from app.os.knowledge.sheets.undo import undo_import
from app.os.registry.store import RegistryStore

from .helpers import COUNTRY, checks, deps, inst, load_list, prog, workbook

pytestmark = pytest.mark.req("R-67")
E = "inst:t-inst-001"


def do_import(engine, path, d):
    return run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")


def facts(engine):
    with engine.connect() as conn:
        return {r.field: r for r in conn.execute(select(models.knowledge_facts).where(
            models.knowledge_facts.c.scope == "programme"))}


def test_a_programme_row_creates_the_programme_its_place_in_the_registry_and_its_facts(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    path = workbook(tmp_path, [inst(1)], programmes=[
        prog(1, "T-INST-001", closing_merit="88.5", closing_scale="100", min_hssc="60%"),
        prog(2, "T-INST-001", seat_category="quota b", seats="7", chk=checks("correct", None))])
    res = do_import(engine, path, d)
    assert res.programmes_created == ["T-PRG-001", "T-PRG-002"]
    p = d.programmes.get("T-PRG-001")
    assert (p.institution_id, p.level, p.region, p.name, p.university, p.route_key) == (
        E, "bachelor", "punjab", "Test Medicine", "Test College 1", "registry")
    assert RegistryStore(engine, "pai").programmes_of(E) == ["T-PRG-001", "T-PRG-002"]
    f = facts(engine)
    assert f["seats_open_merit"].status == "verified" and f["seats_open_merit"].fact_class == "seat_quota"
    assert f["seats_open_merit"].intake_term == "session" and f["seats_open_merit"].intake_year == 2026
    assert f["closing_merit_open_merit"].value == {"value": "88.5", "scale": "100"}
    assert f["min_hssc"].fact_class == "eligibility_threshold"
    assert f["seats_quota_b"].status == "confirmed"  # high-stakes without check 2 is never verified
    assert RegistryStore(engine, "pai").revisions(E)[-1].cause == "import"


def test_a_legacy_punjab_style_sheet_imports_into_the_canonical_programme(engine, clean, tmp_path):
    load_list(engine)
    fmt = load_format()
    wb = openpyxl.Workbook()
    wb.active.title = "Institutions"
    wb.active.append(list(fmt.all_columns("Institutions")))
    row = inst(1)
    wb.active.append([row.get(c) for c in fmt.all_columns("Institutions")])
    wb.create_sheet("Facts").append(list(fmt.all_columns("Facts")))
    ws = wb.create_sheet("Programmes")
    ws.append(["programme_id", "inst_id", "programme", "intake", "open_merit_seats", "total_seats",
               "closing_open_merit_aggregate", "closing_source_url", "seats_source_url", "seats_quote", "retrieved",
               "claude_status", "claude_note", "checker1_result", "checker1_name", "checker2_approved", "checker2_name"])
    ws.append(["PB-1", "T-INST-001", "Test MBBS", "Session 2025-26", "313", "325", "94.8", "https://a.alpha.test/closing",
               "https://a.alpha.test/seats", "| 1 | Test College 1 | 313 |", "2026-11-03", "found", None, "correct",
               "Claude – check 1", "yes", "Claude – check 2 (independent)"])
    path = tmp_path / "punjab.xlsx"
    wb.save(path)
    d = deps(engine)
    res = do_import(engine, path, d)
    assert res.layouts == {"Programmes": "programmes_seats_closing"}
    f = facts(engine)
    assert f["seats_open_merit"].status == "verified" and f["seats_open_merit"].quote == "| 1 | Test College 1 | 313 |"
    assert f["seats_total"].status == "unconfirmed" and f["seats_total"].quote == ""  # the row has no quote for it
    assert f["closing_merit_open_merit"].status == "unconfirmed"
    assert d.programmes.get("PB-1").name == "Test MBBS" and len(res.programmes_created) == 1


def test_undo_withdraws_the_programmes_the_import_created(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    res = do_import(engine, workbook(tmp_path, [inst(1)], programmes=[prog(1, "T-INST-001")]), d)
    r = undo_import(engine, "pai", res.import_id, actor="admin")
    assert (r.programmes, r.facts, r.registry) == (1, 1, 1)
    p = d.programmes.get("T-PRG-001")
    assert p.status == "excluded" and p.institution_id is None
    assert facts(engine)["seats_open_merit"].status == "stale"


def test_a_programme_of_a_rejected_institution_is_rejected_too(engine, clean, tmp_path):
    load_list(engine)
    res = do_import(engine, workbook(tmp_path, [inst(1, region="Narnia")], programmes=[prog(1, "T-INST-001")]), deps(engine))
    assert [r.reason for r in res.rows] == ["unknown_region", "institution_not_loaded"]
    assert res.programmes_created == []
