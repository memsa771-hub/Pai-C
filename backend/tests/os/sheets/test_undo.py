"""P2-T6: undo replays an import's revisions backwards; nothing is deleted (P2 spec §4.6; master R-68; P2-D9)."""

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge.sheets.importer import run_import
from app.os.knowledge.sheets.importlog import ImportLog
from app.os.knowledge.sheets.undo import UndoRefused, undo_import
from app.os.registry.store import RegistryStore

from .helpers import COUNTRY, checks, deps, fact, inst, load_list, workbook

pytestmark = pytest.mark.req("R-68")
E = "inst:t-inst-001"


def do_import(engine, tmp_path, institutions, facts=(), programmes=(), name="a.xlsx", d=None):
    path = workbook(tmp_path, institutions, facts, programmes, name=name)
    return run_import(path, d or deps(engine), mode="owner_accepted", actor="dev", country=COUNTRY,
                      decision_ref="ref-1").import_id


def facts(engine):
    with engine.connect() as conn:
        return {r.field: r for r in conn.execute(select(models.knowledge_facts))}


def test_undo_withdraws_what_the_import_inserted_and_keeps_every_row(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    iid = do_import(engine, tmp_path, [inst(1)], [fact(1, "T-INST-001")], d=d)
    assert facts(engine)["deadline_close"].status == "verified"
    r = undo_import(engine, "pai", iid, actor="admin")
    assert (r.facts, r.registry) == (1, 1)
    f = facts(engine)["deadline_close"]
    assert f.status == "stale" and f.value is None and f.conflict_note == f"withdrawn: import {iid} undone"
    s = RegistryStore(engine, "pai")
    assert s.get(E).status == "closed" and s.get(E).attrs["withdrawn_by_import"] == iid
    revs = d.knowledge.revisions(f.id)
    assert [r.action for r in revs] == ["insert", "status", "undo"] and revs[-1].cause_ref == f"undo-{iid}"
    assert s.revisions(E)[-1].action == "undo"
    rec = ImportLog(engine, "pai").get(iid)
    assert (rec.status, rec.undone_by) == ("undone", "admin") and rec.undone_at
    with pytest.raises(ValueError, match="already undone"):
        undo_import(engine, "pai", iid, actor="admin")


def test_undo_restores_what_the_import_changed(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    first = do_import(engine, tmp_path, [inst(1)], [fact(1, "T-INST-001", value="2027-07-15")], d=d)
    undo_import(engine, "pai", first, actor="admin")  # an undone import may be imported again
    second = do_import(engine, tmp_path, [inst(1, name="Renamed College")], [fact(1, "T-INST-001", value="2027-08-01")],
                       d=d)
    assert facts(engine)["deadline_close"].value["value"] == "2027-08-01"
    third = do_import(engine, tmp_path, [inst(1, name="Renamed Again")],
                      [fact(1, "T-INST-001", value="2027-09-09", chk=checks("unclear", None))], name="b.xlsx", d=d)
    assert facts(engine)["deadline_close"].value["value"] == "2027-09-09"
    with pytest.raises(UndoRefused):  # the second import is no longer the last word
        undo_import(engine, "pai", second, actor="admin")
    undo_import(engine, "pai", third, actor="admin")
    f = facts(engine)["deadline_close"]
    assert f.value["value"] == "2027-08-01" and f.status == "verified"
    assert RegistryStore(engine, "pai").get(E).name == "Renamed College"
    undo_import(engine, "pai", second, actor="admin")
    assert facts(engine)["deadline_close"].status == "stale"


def test_undo_refuses_when_someone_changed_a_fact_after_the_import(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    iid = do_import(engine, tmp_path, [inst(1)], [fact(1, "T-INST-001")], d=d)
    fid = facts(engine)["deadline_close"].id
    d.knowledge.set_status(fid, "stale", cause="monitor")
    with pytest.raises(UndoRefused) as e:
        undo_import(engine, "pai", iid, actor="admin")
    assert e.value.conflicts == [f"fact {fid}"]
    assert facts(engine)["deadline_close"].status == "stale" and ImportLog(engine, "pai").get(iid).status == "done"
    assert RegistryStore(engine, "pai").get(E).status == "active"  # all or nothing


def test_unknown_import(engine, clean):
    with pytest.raises(KeyError):
        undo_import(engine, "pai", 999, actor="admin")


def test_a_withdrawn_fact_does_not_make_an_institution_researched(engine, clean, tmp_path):
    from app.os.registry.coverage import coverage_map

    load_list(engine)
    iid = do_import(engine, tmp_path, [inst(1)], [fact(1, "T-INST-001")])
    assert coverage_map(engine, "pai", 2027)[E].level == "verified"
    undo_import(engine, "pai", iid, actor="admin")
    assert E not in coverage_map(engine, "pai", 2027)  # the institution is closed by the undo too
    iid2 = do_import(engine, tmp_path, [inst(1)], [], name="b.xlsx")
    assert coverage_map(engine, "pai", 2027)[E].level == "listed"  # the withdrawn fact (stale, empty) is not counted
    assert iid2
