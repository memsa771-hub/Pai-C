"""P3-T2 (ADR-001 D4; R-36, R-49): programmes belong to a family by their columns, not by `route_key`.

One helper, `programmes_of(playbook)`, decides which programmes a playbook sees, and every reader of a route's
programmes goes through it. The importer writes the run's `--family` and refuses a row whose lists name another
family; a backfill applies the same rule to programmes imported before. Fictional data only: the family `alphafam` of
tests/os/family_playbooks on the fictional route ZZ -> ZZ, and `.test` domains."""

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import insert, select, update

from app.os import models, ports
from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice
from app.os.contracts.route_contract_v2 import RouteContractV2
from app.os.knowledge.port import Fact
from app.os.knowledge.programmes import Programme, ProgrammeScope, ProgrammeStore, programmes_of
from app.os.knowledge.store import SqlKnowledge
from app.os.playbooks import PLAYBOOK_DIR, load_playbook, load_playbook_dir
from app.os.settings import load_settings

pytestmark = [pytest.mark.req("R-36"), pytest.mark.req("R-49")]

HERE = Path(__file__).parent
FAMILY = HERE / "family_playbooks"
FAKE = HERE / "playbooks"
APP_OS = HERE.parents[1] / "app" / "os"
FAM = load_playbook(FAMILY / "fam_inter.v1.yaml")
FLAG = "CONNECT_FAMILY_ALPHAFAM"
AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
YEAR = 2027
INTAKE = IntakeRef(term="winter", year=YEAR)

# ref -> (route_key, family, level, status): only the first two are the family's at its level
SEED = {
    "fam-p1.test": ("registry", "alphafam", "intermediate", "active"),
    "fam-p2.test": ("registry", "alphafam", "intermediate", "active"),
    "fam-bachelor.test": ("registry", "alphafam", "bachelor", "active"),  # the family at another level
    "beta-p1.test": ("registry", "betafam", "intermediate", "active"),  # another family
    "fam-key.test": (FAM.key, None, None, "active"),  # the playbook's key but no family: not how a family binds
    "fam-off.test": ("registry", "alphafam", "intermediate", "excluded"),
}


def seed(engine, rows=SEED) -> None:
    store = ProgrammeStore(engine, "pai")
    for ref, (route_key, family, level, status) in rows.items():
        store.upsert(Programme(ref=ref, route_key=route_key, university=f"Uni {ref}", name=f"Programme {ref}",
                               aliases=(), start_urls=(f"https://{ref.removesuffix('.test')}.test/p",),
                               official_domains=(f"{ref.removesuffix('.test')}.test",), status=status))
    with engine.begin() as conn:  # the place the registry gives a programme (link_programme writes it in an import)
        for ref, (_, family, level, _) in rows.items():
            conn.execute(update(models.programmes).where(models.programmes.c.ref == ref).values(
                family=family, level=level))


def fact(engine, ref, field, value, status="confirmed", term="winter"):
    SqlKnowledge(engine, "pai").upsert("programme", ref, field, Fact(
        value, "q" if status != "unconfirmed" else "", f"https://{ref.removesuffix('.test')}.test/r", AT, YEAR, status,
        intake_term=term), "manual")


def services(engine, os_db, on=True, books=None):
    from app.os.api.services import make_services

    env = {"OS_DATABASE_URL": os_db} | ({FLAG: "on"} if on else {})
    books = books or (load_playbook_dir(FAKE) | load_playbook_dir() | load_playbook_dir(FAMILY)
                      | load_playbook_dir(FAMILY / "v2"))
    return make_services(load_settings(env), engine=engine, playbooks=books, today=lambda: date(2027, 1, 20))


@pytest.fixture
def fam(engine, clean, os_db):
    seed(engine)
    svc = services(engine, os_db)
    yield svc
    ports.configure(None)


def contract(refs, student="fam-student", source="self_serve", ext="fam-1") -> RouteContractV2:
    return RouteContractV2.model_validate({
        "contract_version": "2", "source": source, "external_ref": ext, "student_ref": student,
        "origin_country": "ZZ", "destination_country": "ZZ", "level": "intermediate",
        "target_intake": {"term": "winter", "year": YEAR},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


# --- the helper ---------------------------------------------------------------------------------------------------------

def test_programmes_of_binds_a_family_playbook_by_family_and_level_and_any_other_by_key():
    assert programmes_of(FAM) == ProgrammeScope(FAM.key, "alphafam", "intermediate")
    for path in [*PLAYBOOK_DIR.glob("*.yaml"), *FAKE.glob("*.yaml")]:
        book = load_playbook(path)
        assert programmes_of(book) == ProgrammeScope(book.key), path.name  # Germany and the fakes: today's match


def row(route_key, family=None, level=None, status="active"):
    return Programme(ref="x", route_key=route_key, university="", name="", aliases=(), start_urls=(),
                     official_domains=(), status=status, family=family, level=level)


def test_scope_holds_the_rule():
    scope = programmes_of(FAM)
    assert scope.holds(row("registry", "alphafam", "intermediate"))
    assert not scope.holds(row("registry", "alphafam", "bachelor"))
    assert not scope.holds(row("registry", "betafam", "intermediate"))
    assert not scope.holds(row(FAM.key))  # the key alone does not bind a family playbook
    assert scope.holds(row(FAM.key, status="requested"))  # a student's request on the route carries only its key
    plain = ProgrammeScope("germany_master")
    assert plain.holds(row("germany_master")) and not plain.holds(row("registry", "alphafam", "intermediate"))


def test_store_and_visible_programmes_see_the_familys_programmes(fam, engine):
    from app.os.knowledge.requests import visible_programmes

    store = ProgrammeStore(engine, "pai")
    assert [p.ref for p in store.active(programmes_of(FAM))] == ["fam-p1.test", "fam-p2.test"]
    assert [p.ref for p in store.active(FAM.key)] == ["fam-key.test"]  # a bare key is today's match
    assert [p.ref for p in visible_programmes(engine, "pai", programmes_of(FAM), YEAR)] == [
        "fam-p1.test", "fam-p2.test"]


def test_a_plain_playbook_sees_exactly_its_route_key_programmes(engine, clean):
    seed(engine, {**SEED, "de-1.test": ("germany_master", None, None, "active"),
                  "de-2.test": ("germany_master", "alphafam", "intermediate", "active")})
    store = ProgrammeStore(engine, "pai")
    for book in load_playbook_dir().values():
        assert store.active(programmes_of(book)) == store.active(book.key), book.key
    germany = next(b for b in load_playbook_dir().values() if b.key == "germany_master")
    assert [p.ref for p in store.active(programmes_of(germany))] == ["de-1.test", "de-2.test"]


# --- every reader, with a family playbook -------------------------------------------------------------------------------

def _intake(svc, export):
    from app.os.adapters.counsellor.intake import process
    from app.os.adapters.counsellor.store import IntakeStore

    store = IntakeStore(svc.engine, "pai")
    store.add(export, "0" * 64)
    return process(svc, store.get(export["decision_id"]))


def _decision(n, refs=("fam-p1.test",)):
    import json

    sample = json.loads((APP_OS / "contracts" / "samples" / "v2" / "decision_chosen_de.json").read_text())
    return {**sample, "decision_id": f"fam-d{n}", "decision_version": n,
            "chosen_at": f"2027-01-{10 + n:02d}T09:00:00+05:00", "origin_country": "ZZ", "destination_country": "ZZ",
            "level": "intermediate", "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]}


def test_counsellor_intake_plans_a_family_decision_instead_of_unknown_programme(fam, monkeypatch):
    seen = []
    real = ProgrammeStore.active

    def spy(self, route):
        seen.append(route)
        return real(self, route)

    monkeypatch.setattr(ProgrammeStore, "active", spy)
    r = _intake(fam, _decision(1, ("fam-p1.test", "fam-p2.test")))
    assert (r.status, r.reason) == ("planned", None)
    assert len(seen) >= 2 and all(s == programmes_of(FAM) for s in seen)  # the adoption check (:260) and the intake
    r = _intake(fam, _decision(2, ("fam-p1.test", "beta-p1.test")))  # a place of another family is still unknown
    assert (r.status, r.reason) == ("refused", "unknown_programme")


def test_self_serve_start_and_swap_take_the_familys_programmes(fam, engine):
    from app.os.routes import builder

    ref = builder.start(fam.plans, "fam-student", FAM.key, INTAKE, [ProgrammeChoice(programme_ref="fam-p1.test", rank=1)])
    with pytest.raises(builder.NotAllowed, match="not a programme of this route"):
        builder.start(fam.plans, "fam-other", FAM.key, INTAKE, [ProgrammeChoice(programme_ref="fam-key.test", rank=1)])
    fact(engine, "fam-p2.test", "offer_date", {"date": "2027-03-01"})
    builder.swap(fam.plans, "fam-student", ref.plan_id, "fam-p1.test", "fam-p2.test")
    contract_, _ = fam.plans._contract(ref.plan_id)
    assert [p.programme_ref for p in contract_.programmes] == ["fam-p2.test"]
    with pytest.raises(builder.NotAllowed, match="not a programme of this route"):
        builder.swap(fam.plans, "fam-student", ref.plan_id, "fam-p2.test", "beta-p1.test")


def test_self_serve_lists_and_cards_read_the_familys_programmes(fam, engine):
    from app.os.api import self_serve

    fact(engine, "fam-p1.test", "offer_date", {"date": "2027-03-01"})
    found = self_serve.route_programmes(fam.plans, "fam-student", FAM.key, YEAR)
    assert [p["ref"] for p in found] == ["fam-p1.test", "fam-p2.test"]
    assert found[0]["research_state"] == "researched" and found[1]["research_state"] == "being_researched"
    assert self_serve.eligibility(fam.plans, "fam-student", "fam-p1.test", FAM.key, YEAR) == {
        "card": None, "suggestions": []}  # the family playbook has no rules; the place is known
    assert self_serve.eligibility(fam.plans, "fam-student", "fam-key.test", FAM.key, YEAR) is None


def test_a_request_on_a_family_route_is_seen_through_the_route_and_finds_a_registry_place(fam, engine):
    from app.os.api import self_serve
    from app.os.knowledge.requests import request_programme

    queued = []
    ref, created = request_programme(engine, "pai", "fam-student", FAM.key, "Uni", "Programme",
                                     "https://fam-p1.test/p", now=AT, enqueue=queued.append, intake_year=YEAR,
                                     scope=programmes_of(FAM))
    assert (ref, created) == ("fam-p1.test", False)  # the registry place, not a second row
    ref, created = request_programme(engine, "pai", "fam-student", FAM.key, "Uni N", "New one",
                                     "https://new.test/p", now=AT, enqueue=queued.append, intake_year=YEAR,
                                     scope=programmes_of(FAM))
    assert created and ref.startswith("req-")
    shown = {p["ref"]: p for p in self_serve.route_programmes(fam.plans, "fam-student", FAM.key, YEAR)}
    assert shown[ref]["requested_by_student"] and shown[ref]["research_state"] == "being_researched"


def test_programme_request_api_on_a_family_route_finds_the_registry_place(engine, clean, os_db):
    from tests.os.test_api_self_serve import P, build_api, me

    seed(engine)
    services(engine, os_db).plans.start_plan(contract(("fam-p1.test",)))  # the student may ask (pinned, T1's rule)
    api = build_api(engine, os_db, extra_books=load_playbook_dir(FAMILY) | load_playbook_dir(FAMILY / "v2"))
    try:
        r = api.post(f"{P}/programmes/requests", headers=me("fam-student"), json={
            "route": FAM.key, "intake_year": YEAR, "university": "Uni", "name": "Programme",
            "url": "https://fam-p1.test/p"})
        assert r.status_code == 202 and r.json() == {"programme_ref": "fam-p1.test", "created": False}
    finally:
        ports.configure(None)


def test_plan_query_lists_v1_and_v2_read_the_familys_programmes(fam):
    from app.os.ports import plan_query

    ports.configure(fam)
    assert [p.programme_ref for p in plan_query.programme_list(FAM.key, INTAKE).programmes] == [
        "fam-p1.test", "fam-p2.test"]
    v2 = plan_query.programme_list_v2(FAM.key, INTAKE)
    assert [(p.programme_ref, p.coverage_level, p.not_run_yet) for p in v2.programmes] == [
        ("fam-p1.test", "listed", True), ("fam-p2.test", "listed", True)]


def test_programme_facts_of_a_family_place_ask_for_the_familys_fields(fam):
    from app.os.compiler.compile import needed_fields
    from app.os.ports import plan_query

    ports.configure(fam)
    facts = plan_query.programme_facts("fam-p1.test", INTAKE)
    wanted = sorted(needed_fields(FAM)[1])
    assert wanted and [f.field for f in facts.facts] == wanted
    assert all(f.level == "missing" for f in facts.facts)


def _eligible_books():
    """The family playbooks with the grade rule of a fake route, so cards and suggestions are made."""
    rules = load_playbook(FAKE / "ireland_master.v1.yaml").eligibility
    books = load_playbook_dir(FAKE) | load_playbook_dir()
    for key, book in (load_playbook_dir(FAMILY) | load_playbook_dir(FAMILY / "v2")).items():
        books[key] = book.model_copy(update={"eligibility": rules})
    return books


def test_eligibility_notes_and_replan_suggest_the_familys_programmes(engine, clean, os_db):
    from app.os.eligibility.notes import NOTES, refresh
    from app.os.outbox import Outbox
    from app.os.documents.store import ProfileStore
    from app.os.replan.apply import Replanner
    from app.os.replan.config import load_replan_configs

    seed(engine)
    svc = services(engine, os_db, books=_eligible_books())
    for ref, need in (("fam-p1.test", 60), ("fam-p2.test", 40), ("fam-key.test", 40), ("beta-p1.test", 40)):
        fact(engine, ref, "grade_requirement", {"percent_min": need})
    profiles = ProfileStore(engine, "pai")
    profiles.set("fam-student", "transcript.percentage", 70, None)
    plan = svc.plans.start_plan(contract(("fam-p1.test",)))
    assert refresh(svc.plans, "fam-student", plan.plan_id)[0] == 0  # the first verdict is only recorded
    profiles.set("fam-student", "transcript.percentage", 50, None)
    assert refresh(svc.plans, "fam-student", plan.plan_id)[0] == 1
    with engine.connect() as conn:
        note = conn.execute(select(NOTES.c.payload)).scalar_one()
    assert note["verdict"] == "likely_below" and note["suggestions"] == ["fam-p2.test"]
    replanner = Replanner(engine, svc.plans, load_replan_configs(), Outbox(engine, "pai"))
    book = svc.plans._pinned(plan.plan_id)
    assert replanner._suggestions(svc.plans._contract(plan.plan_id)[0], book, "fam-p1.test") == ["fam-p2.test"]


def test_term_backfill_finds_the_route_of_a_family_place(engine, clean):
    from app.os.intakes.rollover import backfill_intake_terms

    seed(engine)
    fact(engine, "fam-p1.test", "offer_date", {"date": "2027-03-01"}, term="")
    fact(engine, "beta-p1.test", "offer_date", {"date": "2027-03-01"}, term="")
    books = load_playbook_dir(FAMILY) | load_playbook_dir(FAMILY / "v2")
    res = backfill_intake_terms(engine, "pai", books)
    assert res.updated == 1 and [(s.ref, s.reason) for s in res.skipped] == [("beta-p1.test", "unknown_ref")]
    twin = FAM.model_copy(update={"key": "fam_twin"})  # two keys of one family and level: no term is guessed
    fact(engine, "fam-p2.test", "offer_date", {"date": "2027-03-01"}, term="")
    res = backfill_intake_terms(engine, "pai", books | {(twin.key, 1): twin})
    assert ("fam-p2.test", "several_routes") in {(s.ref, s.reason) for s in res.skipped}


def test_every_reader_of_a_routes_programmes_goes_through_the_helper():
    """A regression guard (ADR-001 §5: a missed reader would refuse every family decision): no OS code reads a route's
    programmes by its key. Each `.active(...)` of the programme store and each `visible_programmes(...)` call passes
    `programmes_of(...)`, and no query compares the programmes' `route_key` itself, outside the helper."""
    calls = re.compile(r"ProgrammeStore\([^)]*\)\.active\((?!programmes_of\()|visible_programmes\([^,]+,[^,]+,\s*"
                       r"(?!programmes_of\()")
    direct = re.compile(r"\b(P|G|T|PG|programmes)\.c\.route_key\s*==")
    found = []
    for path in APP_OS.rglob("*.py"):
        rel = path.relative_to(APP_OS).as_posix()
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if rel in ("knowledge/programmes.py",) or line.lstrip().startswith(("def ", "#")):
                continue
            if calls.search(line):
                found.append(f"{rel}:{n}")
            if direct.search(line):
                found.append(f"{rel}:{n}")
    assert found == []


# --- the importer ------------------------------------------------------------------------------------------------------

def _import(engine, tmp_path, family, name="batch.xlsx", **list_attrs):
    from app.os.knowledge.sheets.importer import run_import
    from tests.os.sheets.helpers import COUNTRY, deps, inst, load_list, prog, workbook

    load_list(engine, **list_attrs)
    path = workbook(tmp_path, [inst(1)], programmes=[prog(1, "T-INST-001", level="intermediate")], name=name)
    d = deps(engine)
    return run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref="ref-1",
                      family=family), d


def test_the_importer_writes_the_runs_family(engine, clean, tmp_path):
    res, d = _import(engine, tmp_path, "intermediate", family="intermediate")
    p = d.programmes.get("T-PRG-001")
    assert (p.family, p.level, p.route_key) == ("intermediate", "intermediate", "registry")
    book = FAM.model_copy(update={"family": "intermediate"})
    assert [x.ref for x in d.programmes.active(programmes_of(book))] == ["T-PRG-001"]
    from app.os.registry.store import RegistryStore

    rev = RegistryStore(engine, "pai").revisions("inst:t-inst-001")[-1]
    assert rev.kind == "programme" and rev.after["family"] == "intermediate" and rev.cause_ref == f"import-{res.import_id}"


def test_the_importer_writes_the_family_of_a_list_without_one(engine, clean, tmp_path):
    _, d = _import(engine, tmp_path, "intermediate")  # the list names no family: the run's is written
    assert d.programmes.get("T-PRG-001").family == "intermediate"


def test_the_importer_refuses_a_row_whose_lists_name_another_family(engine, clean, tmp_path):
    res, d = _import(engine, tmp_path, "intermediate", family="bachelor")
    prog = next(r for r in res.rows if r.sheet == "Programmes")
    assert (prog.bucket, prog.reason) == ("rejected", "family_conflicts_with_list")
    assert "bachelor" in prog.detail and d.programmes.get("T-PRG-001") is None


def test_without_family_the_importer_writes_none_as_before(engine, clean, tmp_path):
    _, d = _import(engine, tmp_path, "", family="bachelor")
    p = d.programmes.get("T-PRG-001")
    assert p.family is None and p.level == "intermediate"


def test_the_import_command_says_when_no_family_is_given(tmp_path):
    from scripts.os_import_batch import main
    from tests.os.sheets.helpers import COUNTRY, inst, prog, workbook

    path = workbook(tmp_path, [inst(1)], programmes=[prog(1, "T-INST-001")])
    out: list[str] = []
    assert main(["validate", str(path), "--country", COUNTRY], out=out.append) == 0
    assert any(line.startswith("family: none given") for line in out)
    out.clear()
    main(["validate", str(path), "--country", COUNTRY, "--family", "intermediate"], out=out.append)
    assert not any(line.startswith("family: none given") for line in out)


# --- the backfill ------------------------------------------------------------------------------------------------------

def _family(engine, ref="T-PRG-001"):
    with engine.connect() as conn:
        return conn.execute(select(models.programmes.c.family).where(models.programmes.c.ref == ref)).scalar_one()


def _cli(engine, *argv):
    from scripts.os_programme_family_backfill import main

    out: list[str] = []
    code = main(list(argv), engine=engine, tenant_id="pai", out=out.append)
    return code, "\n".join(out)


def test_backfill_dry_run_apply_and_undo(engine, clean, tmp_path):
    from app.os.registry.store import RegistryStore

    res, _ = _import(engine, tmp_path, "", family="intermediate")  # an import from before P3-T2: no family written
    assert _family(engine) is None
    code, text = _cli(engine, "--family", "intermediate", "--import", str(res.import_id))
    assert code == 0 and "would set T-PRG-001: family (none) -> intermediate" in text and "dry run" in text
    assert _family(engine) is None  # a dry run writes nothing
    code, text = _cli(engine, "--family", "intermediate", "--import", str(res.import_id), "--apply")
    ref = re.search(r"applied as (family-backfill-\S+)", text).group(1)
    assert code == 0 and _family(engine) == "intermediate"
    rev = RegistryStore(engine, "pai").revisions("inst:t-inst-001")[-1]
    assert (rev.kind, rev.subject, rev.cause_ref, rev.before["family"], rev.after["family"]) == (
        "programme", "T-PRG-001", ref, None, "intermediate")
    code, text = _cli(engine, "--family", "intermediate", "--import", str(res.import_id))
    assert "0 change(s)" in text and "1 already intermediate" in text  # safe to run again
    code, text = _cli(engine, "--undo", ref)
    assert code == 0 and "restored T-PRG-001" in text and _family(engine) is None
    rev = RegistryStore(engine, "pai").revisions("inst:t-inst-001")[-1]
    assert rev.cause_ref == f"undo-{ref}" and rev.after["family"] is None
    code, text = _cli(engine, "--undo", ref)
    assert code == 2 and "already undone" in text
    from app.os.knowledge.sheets.undo import undo_import

    undo_import(engine, "pai", res.import_id, actor="admin")  # an undone backfill is no change after the import


def test_backfill_leaves_a_conflicting_or_already_set_programme_alone(engine, clean, tmp_path):
    from app.os.knowledge.family_backfill import run_backfill

    res, _ = _import(engine, tmp_path, "", family="bachelor")
    out = run_backfill(engine, "pai", family="intermediate", imports=[res.import_id], apply=True)
    assert out.changes == [] and [(s.ref, s.reason) for s in out.skipped] == [
        ("T-PRG-001", "family_conflicts_with_list")] and not out.applied
    assert _family(engine) is None
    with engine.begin() as conn:
        conn.execute(update(models.programmes).where(models.programmes.c.ref == "T-PRG-001").values(family="bachelor"))
    out = run_backfill(engine, "pai", family="intermediate", imports=[res.import_id])
    assert [(s.ref, s.reason) for s in out.skipped] == [("T-PRG-001", "family_already_set")]


def test_backfill_refuses_bad_input_and_an_undo_after_a_later_change(engine, clean, tmp_path):
    from app.os.knowledge.family_backfill import BackfillRefused, run_backfill, undo_backfill
    from app.os.registry.store import RegistryStore

    res, _ = _import(engine, tmp_path, "")
    with pytest.raises(BackfillRefused, match="name the imports"):
        run_backfill(engine, "pai", family="intermediate", imports=[])
    with pytest.raises(BackfillRefused, match="not a family code"):
        run_backfill(engine, "pai", family="Inter Mediate", imports=[res.import_id])
    with pytest.raises(BackfillRefused, match="does not exist"):
        run_backfill(engine, "pai", family="intermediate", imports=[res.import_id + 99])
    out = run_backfill(engine, "pai", family="intermediate", imports=[res.import_id], apply=True)
    RegistryStore(engine, "pai").link_programme("T-PRG-001", institution_id="inst:t-inst-001", field="later",
                                                 cause="review", cause_ref="later-edit")
    with pytest.raises(BackfillRefused, match="changed after the backfill: T-PRG-001"):
        undo_backfill(engine, "pai", out.cause_ref)
    assert _family(engine) == "intermediate"
    with pytest.raises(BackfillRefused, match="no backfill run"):
        undo_backfill(engine, "pai", "family-backfill-never")


def test_backfill_touches_only_the_named_imports(engine, clean, tmp_path):
    from app.os.knowledge.family_backfill import run_backfill

    res, _ = _import(engine, tmp_path, "")
    with engine.begin() as conn:  # a programme no import placed (a seed): never touched
        conn.execute(insert(models.programmes).values(tenant_id="pai", ref="seeded.test", route_key="registry",
                                                      university="u", name="n"))
    out = run_backfill(engine, "pai", family="intermediate", imports=[res.import_id], apply=True)
    assert [c.ref for c in out.changes] == ["T-PRG-001"] and _family(engine, "seeded.test") is None
