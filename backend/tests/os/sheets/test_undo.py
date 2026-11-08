"""P2-T6: undo replays an import's revisions backwards; nothing is deleted (P2 spec §4.6; master R-68; P2-D9)."""

import pytest
from sqlalchemy import select

from app.os import models
from app.os.knowledge.sheets.importer import AlreadyImported, run_import
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


# --- every kind of revision the import writes (programme placement, links, failed imports) ----------------------------


def programme_cols(engine, ref):
    with engine.connect() as conn:
        return dict(conn.execute(select(*[models.programmes.c[c] for c in (
            "institution_id", "campus_id", "level", "field", "family", "region", "status")]).where(
            models.programmes.c.ref == ref)).one()._mapping)


def test_scenario_a_the_institution_exists_and_the_import_only_places_programmes(engine, clean, tmp_path):
    from .helpers import prog

    load_list(engine)
    d = deps(engine)
    do_import(engine, tmp_path, [inst(1)], d=d)  # the institution is in the registry already
    s = RegistryStore(engine, "pai")
    before_revs = [r.id for r in s.revisions(E)]
    iid = do_import(engine, tmp_path, [], programmes=[prog(1, "T-INST-001")], name="p.xlsx", d=d)
    assert programme_cols(engine, "T-PRG-001")["institution_id"] == E and s.programmes_of(E) == ["T-PRG-001"]
    assert [r.kind for r in s.revisions(E) if r.id not in before_revs] == ["programme"]
    r = undo_import(engine, "pai", iid, actor="admin")
    assert (r.programmes, r.registry) == (1, 0)  # only the programme moves; the institution row is untouched
    assert programme_cols(engine, "T-PRG-001") == {
        "institution_id": None, "campus_id": None, "level": None, "field": None, "family": None, "region": None,
        "status": "excluded"}
    assert s.get(E).status == "active" and s.programmes_of(E) == []
    assert [x.kind for x in s.revisions(E)][-1] == "programme" and s.revisions(E)[-1].action == "undo"
    assert facts(engine)["seats_open_merit"].status == "stale"


def test_scenario_b_the_import_re_links_an_existing_programme(engine, clean, tmp_path):
    from .helpers import prog

    load_list(engine)
    d = deps(engine)
    do_import(engine, tmp_path, [inst(1), inst(2, region="Sindh")], programmes=[prog(1, "T-INST-001")], d=d)
    s = RegistryStore(engine, "pai")
    assert programme_cols(engine, "T-PRG-001")["institution_id"] == E
    iid = do_import(engine, tmp_path, [], programmes=[prog(1, "T-INST-002", level="master")], name="b.xlsx", d=d)
    moved = programme_cols(engine, "T-PRG-001")
    assert (moved["institution_id"], moved["level"], moved["region"]) == ("inst:t-inst-002", "master", "sindh")
    undo_import(engine, "pai", iid, actor="admin")
    back = programme_cols(engine, "T-PRG-001")
    assert (back["institution_id"], back["level"], back["region"], back["status"]) == (E, "bachelor", "punjab", "active")
    assert s.programmes_of(E) == ["T-PRG-001"] and s.programmes_of("inst:t-inst-002") == []


def test_links_the_import_added_are_taken_away_by_the_undo(engine, clean, tmp_path):
    from app.os.registry.store import RegistryStore as RS
    from tests.os.registry.helpers import child

    load_list(engine)
    d = deps(engine)
    do_import(engine, tmp_path, [inst(1)], d=d)
    s = RS(engine, "pai")
    s.record(child("admission_system", "sys", "central-merit", None), cause="import")
    s.link("sys:central-merit", "admits", E, cause="import", cause_ref="import-77", actor="dev")  # an import's link
    with engine.begin() as conn:  # make "import 77" a real, done import so that its link revision belongs to it
        conn.execute(models.imports.insert().values(
            id=77, tenant_id="pai", file_name="x.xlsx", sha256="7" * 64, mode="reviewers", batch_ref="b", actor="dev",
            status="done"))
    r = undo_import(engine, "pai", 77, actor="admin")
    assert r.links == 1 and s.links_from("sys:central-merit") == []
    last = s.revisions("sys:central-merit")[-1]
    assert (last.kind, last.action, last.subject) == ("link", "undo", f"admits:registry:{E}")


def test_the_undo_marks_the_import_undone_in_its_own_transaction(engine, clean, tmp_path, monkeypatch):
    load_list(engine)
    iid = do_import(engine, tmp_path, [inst(1)], [fact(1, "T-INST-001")])
    from app.os.knowledge.sheets import undo as undo_module

    def boom(self, import_id, by, conn=None):
        raise RuntimeError("log failed")

    monkeypatch.setattr(undo_module.ImportLog, "mark_undone", boom)
    with pytest.raises(RuntimeError):
        undo_import(engine, "pai", iid, actor="admin")
    # the data was not touched either: the whole undo rolled back with the failed log update
    assert facts(engine)["deadline_close"].status == "verified" and RegistryStore(engine, "pai").get(E).status == "active"
    assert ImportLog(engine, "pai").get(iid).status == "done"


class Boom(Exception):
    pass


class ExplodingDisputes:
    def open_item(self, kind, **kw):
        raise Boom("queue is down")


def test_a_failed_import_stays_live_and_can_be_undone_then_repeated(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine, disputes=ExplodingDisputes())
    path = workbook(tmp_path, [inst(1)], [fact(1, "T-INST-001"), fact(2, "T-INST-001", field_="odd", intake="standing")])
    with pytest.raises(Boom):
        run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1")
    log = ImportLog(engine, "pai")
    [rec] = log.list()
    assert rec.status == "failed" and "queue is down" in rec.error
    assert RegistryStore(engine, "pai").get(E) is not None  # what it loaded before it failed is there
    with pytest.raises(AlreadyImported):  # a failed import is live: the same file is not imported again on top of it
        run_import(path, deps(engine, disputes=FakeDisputesOK()), mode="owner_accepted", actor="dev", country=COUNTRY,
                   decision_ref="ref-1")
    r = undo_import(engine, "pai", rec.id, actor="admin")  # undo handles a failed import
    assert r.registry == 1 and log.get(rec.id).status == "undone"
    ok = run_import(path, deps(engine, disputes=FakeDisputesOK()), mode="owner_accepted", actor="dev", country=COUNTRY,
                    decision_ref="ref-1")
    assert ok.import_id != rec.id and ImportLog(engine, "pai").get(ok.import_id).status == "done"


class FakeDisputesOK:
    def open_item(self, kind, **kw):
        return 1, True
