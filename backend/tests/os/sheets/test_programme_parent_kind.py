"""P2-T18: a Programmes row whose inst_id names an entity that is not an institution (an admission system, a board) is a
rejected row in the dry run and the import alike, never a failed import; its facts are not loaded (P2 spec §4.1, §4.6;
master R-33, R-67, R-68). Fictional data."""

import pytest

from app.os.knowledge.sheets.importer import build_context, plan_file, run_import
from app.os.knowledge.sheets.importlog import ImportLog
from app.os.registry.store import RegistryError, RegistryStore

from .helpers import COUNTRY, deps, fact, inst, load_list, prog, workbook

pytestmark = [pytest.mark.req("R-33"), pytest.mark.req("R-67"), pytest.mark.req("R-68")]
SYS = "sys:t-sys-001"


def system(**kw) -> dict:
    row = inst(9, ctype="admission_system", source_url="https://admissions.alpha.test/about", **kw)
    row.update(inst_id="T-SYS-001", name="Test admission system")
    return row


def rows_of(results, sheets=("Programmes", "Facts")):
    return {(r.sheet, r.row_id): (r.bucket, r.reason) for r in results if r.sheet in sheets}


def import_(engine, path, d=None):
    return run_import(path, d or deps(engine), mode="owner_accepted", actor="dev", country=COUNTRY,
                      decision_ref="ref-1")


def a_file(tmp_path, name="a.xlsx", institutions=None):
    return workbook(tmp_path, [inst(1), system()] if institutions is None else institutions,
                    [fact(1, "T-PRG-001"), fact(2, "T-PRG-002")],
                    [prog(1, "T-INST-001"), prog(2, "T-SYS-001")], name=name)


def test_a_programme_under_an_admission_system_is_rejected_in_the_dry_run(tmp_path):
    ctx = build_context(None, country=COUNTRY, mode="owner_accepted", batch_ref="b", family="", require_list=False,
                        decision_ref="ref-1")
    res = plan_file(a_file(tmp_path), ctx)[1]
    by = rows_of(res)
    assert by[("Programmes", "T-PRG-001")][0] == "accepted"
    assert by[("Programmes", "T-PRG-002")] == ("rejected", "parent_not_institution")
    detail = next(r.detail for r in res if r.row_id == "T-PRG-002")
    assert "admission_system" in detail and "T-SYS-001" in detail  # the kind and the id are named
    assert by[("Facts", "T-F-001")][0] == "accepted"
    assert by[("Facts", "T-F-002")] == ("rejected", "programme_not_loaded")  # the existing rule for its facts


def test_the_import_rejects_the_same_row_and_loads_the_rest(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    path = a_file(tmp_path)
    ctx = build_context(d, country=COUNTRY, mode="owner_accepted", batch_ref="b", family="", decision_ref="ref-1")
    planned = rows_of(plan_file(path, ctx)[1])
    res = import_(engine, path, d)
    assert ImportLog(engine, "pai").get(res.import_id).status == "done"  # one bad row never fails the file
    assert rows_of(res.rows) == planned  # the import does what the dry run said
    assert planned[("Programmes", "T-PRG-002")] == ("rejected", "parent_not_institution")
    assert planned[("Facts", "T-F-002")] == ("rejected", "programme_not_loaded")
    assert res.programmes_created == ["T-PRG-001"] and d.programmes.get("T-PRG-002") is None
    s = RegistryStore(engine, "pai")
    assert s.get(SYS).kind == "admission_system"  # the system itself is loaded; only the programme is refused
    assert s.programmes_of("inst:t-inst-001") == ["T-PRG-001"]


def test_an_admission_system_already_in_the_registry_is_known_by_its_stored_kind(engine, clean, tmp_path):
    load_list(engine)
    import_(engine, workbook(tmp_path, [inst(1), system()], name="first.xlsx"))
    res = import_(engine, a_file(tmp_path, "second.xlsx", institutions=[]))
    by = rows_of(res.rows)
    assert by[("Programmes", "T-PRG-001")][0] == "accepted"
    assert by[("Programmes", "T-PRG-002")] == ("rejected", "parent_not_institution")
    assert by[("Facts", "T-F-002")] == ("rejected", "programme_not_loaded")
    assert ImportLog(engine, "pai").get(res.import_id).status == "done"


def test_backstop_a_programme_the_registry_refuses_is_a_rejected_row_and_the_import_goes_on(
        engine, clean, tmp_path, monkeypatch):
    load_list(engine)
    d = deps(engine)
    real = d.registry.link_programme

    def refuse(ref, **kw):
        if ref == "T-PRG-001":
            raise RegistryError(f"{ref}: refused by the test")
        return real(ref, **kw)

    monkeypatch.setattr(d.registry, "link_programme", refuse)
    path = workbook(tmp_path, [inst(1), inst(2)], [fact(1, "T-PRG-001"), fact(2, "T-PRG-002")],
                    [prog(1, "T-INST-001"), prog(2, "T-INST-002")], name="a.xlsx")
    res = import_(engine, path, d)
    rec = ImportLog(engine, "pai").get(res.import_id)
    assert rec.status == "done" and "registry_refused" in rec.report_csv  # reported, never silent
    by = rows_of(res.rows)
    assert by[("Programmes", "T-PRG-001")] == ("rejected", "registry_refused")
    assert by[("Programmes", "T-PRG-002")][0] == "accepted"
    assert by[("Facts", "T-F-001")] == ("rejected", "programme_not_loaded")  # no fact on a programme left unplaced
    assert by[("Facts", "T-F-002")][0] == "accepted"
    assert RegistryStore(engine, "pai").programmes_of("inst:t-inst-002") == ["T-PRG-002"]


def test_backstop_an_entity_of_another_kind_is_refused_before_the_programme_is_created(
        engine, clean, tmp_path, monkeypatch):
    """When the plan cannot know the kind (no meta), the import still refuses the row before anything is written."""
    load_list(engine)
    d = deps(engine)
    import_(engine, workbook(tmp_path, [system()], name="first.xlsx"), d)
    ctx = build_context(d, country=COUNTRY, mode="owner_accepted", batch_ref="b", family="", decision_ref="ref-1")
    ctx.registry_info = lambda rid: None  # the kind is unknown to the plan
    monkeypatch.setattr("app.os.knowledge.sheets.importer.build_context", lambda *a, **k: ctx)
    path = workbook(tmp_path, [], [fact(2, "T-PRG-002")], [prog(2, "T-SYS-001")], name="second.xlsx")
    res = import_(engine, path, d)
    assert ImportLog(engine, "pai").get(res.import_id).status == "done"
    by = rows_of(res.rows)
    assert by[("Programmes", "T-PRG-002")] == ("rejected", "registry_refused")
    assert by[("Facts", "T-F-002")] == ("rejected", "programme_not_loaded")
    assert res.programmes_created == [] and d.programmes.get("T-PRG-002") is None
