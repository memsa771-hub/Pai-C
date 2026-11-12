"""P2 integration: the seams the tasks left for each other (T2 registry, T3 sources, T5 review queue, T8 intakes, T10
merit) and the single migration chain. Fictional values only."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, inspect

from app.os.contracts.route_contract import IntakeRef
from app.os.db import OS_SCHEMA
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.regions import normalise_region
from app.os.knowledge.review import ReviewQueue, ReviewerStore
from app.os.knowledge.review.hooks import open_suspect_item
from app.os.knowledge.sources.allowlist import NotApproved, SourceDomains
from app.os.knowledge.sources.snapshots import SnapshotStore
from app.os.knowledge.sources.suspect import SourceGuard
from app.os.ports import plan_query
from tests.os.conftest import run_alembic
from tests.os.registry.helpers import inst, olist, store
from tests.os.test_p2_merit_ports import INTAKE, put, world  # noqa: F401  (a fixture: three fake programmes)

AT = datetime(2026, 11, 1, 9, tzinfo=UTC)
URL, QUOTE = "https://admissions.alpha.test/n", "Apply by 15 July 2027"
PDF = b"%PDF-1.4 original"


@pytest.mark.req("R-76")
@pytest.mark.parametrize("spelling, code", [
    ("ICT (multi-campus)", "islamabad_capital_territory"), ("Islamabad / federal", "islamabad_capital_territory"),
    ("National (private)", "national"), ("Punjab (federal)", "punjab"), ("ict (Multi-Campus)", "islamabad_capital_territory"),
])
def test_region_aliases_from_the_research_batches(spelling, code):
    assert normalise_region(spelling, "PK") == code


def test_one_migration_chain_and_each_step_goes_back(os_db, engine, clean):
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from tests.os.conftest import BACKEND

    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    chain = []
    rev = script.get_revision("os_0029")
    while rev is not None and rev.revision >= "os_0026":
        chain.append(rev.revision)
        rev = script.get_revision(rev.down_revision) if rev.down_revision else None
    assert chain == ["os_0029", "os_0028", "os_0027", "os_0026"]
    engine.dispose()
    for step in ("os_0028", "os_0027", "os_0026", "os_0025"):  # every migration has a working downgrade
        run_alembic(["downgrade", step], os_db)
    eng = create_engine(os_db)
    try:
        names = set(inspect(eng).get_table_names(schema=OS_SCHEMA))
        assert not names & {"os_registry", "os_source_domains", "os_reviewers", "os_intakes"}
    finally:
        eng.dispose()
    run_alembic(["upgrade", "os@head"], os_db)


def test_review_screen_reads_t3_snapshots_and_their_original(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    q = ReviewQueue(engine, "pai", kb)
    reviewer, _ = ReviewerStore(engine, "pai").add("amina", "Amina", "checker")
    fid = kb.upsert("programme", "p1", "deadline_close", Fact({"date": "2027-07-15"}, QUOTE, URL, AT, 2027, "confirmed"))
    item, _ = q.open_verify(fid)
    assert q.detail(item, reviewer)["snapshot"] is None
    snap = SnapshotStore(engine, "pai").save(URL, f"Admissions\n{QUOTE} online.", content_type="application/pdf",
                                             read_method="ocr", original=PDF, original_type="application/pdf")
    got = q.detail(item, reviewer)["snapshot"]
    assert (got["snapshot_id"], got["read_method"], got["quote_found"], got["original_type"]) == (
        snap.id, "ocr", True, "application/pdf")
    assert q.snapshot_original(snap.id) == (PDF, "application/pdf")
    SnapshotStore(engine, "pai").save(URL, "Admissions\nA different notice.", flagged="off_list_links")
    assert q.detail(item, reviewer)["snapshot"]["flagged"] == "off_list_links"  # the newest read, flagged or not


def test_a_suspect_domain_opens_a_review_item_and_only_approvers_reactivate(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    q = ReviewQueue(engine, "pai", kb)
    guard = SourceGuard(engine, "pai", on_suspect=open_suspect_item(q))
    case = guard.flag_domain("spam.test", "link_farm", "forty links off the list", url="https://spam.test/p")
    assert case is not None
    [item] = q.list_items(kind="suspect_domain")
    assert (item.subject, item.payload["reason"], item.payload["url"]) == ("spam.test", "link_farm", "https://spam.test/p")
    assert guard.flag_domain("spam.test", "link_farm") is None and len(q.list_items(kind="suspect_domain")) == 1
    rs = ReviewerStore(engine, "pai")
    for ref, role, kind in (("amina", "checker", "person"), ("bilal", "approver", "person"), ("owner", "admin", "person")):
        rs.add(ref, ref, role, kind)
    assert [rs.is_approver(r) for r in ("amina", "BILAL", "owner", "nobody")] == [False, True, True, False]
    domains = SourceDomains(engine, "pai")
    with pytest.raises(NotApproved):  # a checker is not an approver
        domains.reactivate("spam.test", requested_by="amina", approved_by="bilal", is_approver=rs.is_approver)
    assert domains.reactivate("spam.test", requested_by="bilal", approved_by="owner", is_approver=rs.is_approver) == 1
    rs.set_active("bilal", False)
    assert not rs.is_approver("bilal")


@pytest.mark.req("R-34")
def test_programme_list_v2_uses_the_registry_coverage_and_region(world, engine):
    s = store(engine)
    s.record(olist(rows=2), cause="import")
    s.record(inst("one", region="punjab"), cause="import")
    s.record(inst("two", region="sindh", attrs={"not_readable": True}), cause="import")  # no official online information
    s.link_programme("ie-1", institution_id="inst:one", cause="import")
    s.link_programme("ie-2", institution_id="inst:two", region="sindh", cause="import")
    put(world, "ie-1", "deadline_close", {"date": "2027-07-15"}, verified=True)
    put(world, "ie-2", "deadline_close", {"date": "2027-07-15"}, verified=True)
    put(world, "ie-3", "deadline_close", {"date": "2027-07-15"})
    by = {p.programme_ref: p for p in plan_query.programme_list_v2("ireland_master", INTAKE).programmes}
    assert (by["ie-1"].coverage_level, by["ie-1"].region) == ("verified", "punjab")  # the institution's region
    assert (by["ie-2"].coverage_level, by["ie-2"].region) == ("listed", "sindh")  # R-35d: not readable stays listed
    assert by["ie-2"].not_run_yet
    assert (by["ie-3"].coverage_level, by["ie-3"].region) == ("researched", None)  # not in the registry


def test_self_serve_term_helper_reads_only_a_single_term_route():
    from app.os.api.self_serve import _term

    assert _term(SimpleNamespace(intake_terms=["winter"])) == "winter"
    assert _term(SimpleNamespace(intake_terms=["winter", "summer"])) is None
    assert _term(SimpleNamespace(intake_terms=[])) is None
