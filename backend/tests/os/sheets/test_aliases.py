"""P2-T13: alias files. An id inside a returned file names an entity loaded under another id, without editing the file
(P2 spec §4.6; master R-67, R-68, R-76). Aliases are judged by reviewer attestation of the alias file's own ref, whatever
the mode of the rows. Fictional ids and institutions only."""

from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from app.os import models
from app.os.api.imports import record_out
from app.os.knowledge.review import ReviewerStore, ReviewQueue
from app.os.knowledge.sheets.aliases import AliasError, load_aliases
from app.os.knowledge.sheets.importer import build_context, plan_file, run_import
from app.os.knowledge.sheets.importlog import ImportLog
from app.os.knowledge.sheets.plan import OWNER_ACCEPTED, REVIEWERS
from app.os.knowledge.sheets.reader import file_sha256
from app.os.knowledge.sheets.undo import undo_import
from app.os.knowledge.store import SqlKnowledge
from app.os.registry.store import RegistryStore
from scripts.os_import_batch import main

from .helpers import C1, C2, COUNTRY, deps, fact, inst, load_list, prog, waiver_fmt, workbook

pytestmark = [pytest.mark.req("R-68"), pytest.mark.req("R-67"), pytest.mark.req("R-76")]
DECISION = "owner chat 2026-11-07"
TARGET = "inst:t-inst-001"
A1, A2 = "alias_checker_a", "alias_checker_b"  # reviewer refs of the two alias checks
ROWS_REF = "test-batch-ref"
EVIDENCE = {"url": "https://admissions.alpha.test/about", "quote": "Test College 1, formerly known as Test Uni X"}


def alias(frm="T-UNI-X", to="T-INST-001", c1="correct", c2="yes", n1=A1, n2=A2) -> dict:
    return {"from": frm, "to": to, "evidence": dict(EVIDENCE), "check1": {"result": c1, "name": n1, "date": "2026-11-12"},
            "check2": {"approved": c2, "name": n2, "date": "2026-11-12"}}


def alias_file(tmp: Path, batch: Path, *aliases: dict, sha: str | None = None, name="aliases.yaml") -> Path:
    p = tmp / name
    p.write_text(yaml.safe_dump({"file": batch.name, "sha256": sha or file_sha256(batch), "aliases": list(aliases)},
                                allow_unicode=True), encoding="utf-8")
    return p


def attested(*alias_paths: Path, names=(A1, A2), rows=()):
    """A review-queue stub: `names` attested each alias file's ref; `rows` attested the batch ref of the rows."""
    ok = {(n, load_aliases(p).attest_ref) for p in alias_paths for n in names} | {(n, ROWS_REF) for n in rows}
    return lambda name, ref: (name, ref) in ok


def aliased_rows():
    """A batch naming T-UNI-X: its own row has no quote (it would be rejected); a programme and a fact name it."""
    return ([inst(9, inst_id="T-UNI-X", source_quote=None)], [fact(1, "T-UNI-X")], [prog(1, "T-UNI-X")])


def dry_run(path: Path, *alias_paths: Path, att=None, mode=OWNER_ACCEPTED):
    ctx = build_context(None, country=COUNTRY, mode=mode, batch_ref=ROWS_REF, family="", require_list=False)
    ctx.aliases = tuple(load_aliases(a) for a in alias_paths)
    ctx.attested = att if att is not None else attested(*alias_paths)
    return plan_file(path, ctx)[1]


def by_sheet(results, sheet):
    return [(r.row_id, r.bucket, r.reason, r.detail) for r in results if r.sheet == sheet]


def imp(path, d, aliases=(), fmt=None):
    return run_import(path, d, mode="owner_accepted", actor="dev", country=COUNTRY, decision_ref=DECISION,
                      aliases=aliases, fmt=fmt)


def fact_row(engine, field):
    with engine.connect() as conn:
        return conn.execute(select(models.knowledge_facts).where(models.knowledge_facts.c.field == field)).one()


@pytest.mark.parametrize("mode", [OWNER_ACCEPTED, REVIEWERS])
def test_aliased_row_is_skipped_and_rows_naming_it_load_against_the_target_in_the_same_file(tmp_path, mode):
    institutions, facts, programmes = aliased_rows()
    path = workbook(tmp_path, [inst(1), *institutions], facts, programmes)
    afile = alias_file(tmp_path, path, alias())
    rows = (C1, C2) if mode == REVIEWERS else ()  # in reviewers mode the rows' own checkers attested the batch
    results = dry_run(path, afile, att=attested(afile, rows=rows), mode=mode)
    assert by_sheet(results, "Aliases") == [("T-UNI-X", "accepted", "alias_applied", "T-UNI-X -> T-INST-001")]
    assert ("T-UNI-X", "skipped", "aliased", "T-INST-001") in by_sheet(results, "Institutions")
    prg = next(r for r in results if r.sheet == "Programmes")
    fct = next(r for r in results if r.sheet == "Facts")
    assert (prg.bucket, prg.payload["inst_registry_id"]) == ("accepted", TARGET)
    assert (fct.bucket, fct.payload["ref"]) == ("accepted", TARGET)
    assert fct.payload["row"]["entity_id"] == "T-UNI-X" and "_alias" not in fct.payload["row"]  # the file's own row
    used = fct.payload["provenance"]["alias"]
    assert (used["from"], used["checker1"], used["checker2"], used["evidence"]) == ("T-UNI-X", A1, A2, EVIDENCE)


def test_without_the_alias_file_those_rows_fail(tmp_path):
    institutions, facts, programmes = aliased_rows()
    path = workbook(tmp_path, [inst(1), *institutions], facts, programmes)
    results = dry_run(path)
    assert [r[2] for r in by_sheet(results, "Institutions")] == ["both_checks", "no_quote"]
    assert [r[2] for r in by_sheet(results, "Programmes")] == ["institution_not_loaded"]
    assert [r[2] for r in by_sheet(results, "Facts")] == ["entity_unknown"]


@pytest.mark.parametrize("bad, names", [
    ({"c1": "unclear"}, (A1, A2)), ({"c1": "wrong"}, (A1, A2)), ({"c2": "no"}, (A1, A2)), ({"c2": None}, (A1, A2)),
    ({}, (A1,)), ({}, (A2,)), ({}, ()),  # a checker who has not attested the alias file
    ({"n2": A1}, (A1, A2)),  # checker 2 is checker 1
    ({"n1": C1, "n2": C2}, ()),  # the owner-accepted names of the rows never accept an alias
])
@pytest.mark.parametrize("mode", [OWNER_ACCEPTED, REVIEWERS])
def test_an_alias_not_accepted_by_both_attested_checks_is_ignored_and_reported(tmp_path, bad, names, mode):
    institutions, facts, programmes = aliased_rows()
    path = workbook(tmp_path, [inst(1), *institutions], facts, programmes)
    afile = alias_file(tmp_path, path, alias(**bad))
    rows = (C1, C2) if mode == REVIEWERS else ()
    without = dry_run(path, att=attested(rows=rows), mode=mode)
    with_file = dry_run(path, afile, att=attested(afile, names=names, rows=rows), mode=mode)
    [(rid, bucket, reason, _)] = by_sheet(with_file, "Aliases")
    assert (rid, bucket, reason) == ("T-UNI-X", "skipped", "alias_not_accepted")
    for sheet in ("Institutions", "Programmes", "Facts"):
        assert by_sheet(with_file, sheet) == by_sheet(without, sheet)


def test_an_attestation_of_another_ref_does_not_accept_an_alias(tmp_path):
    path = workbook(tmp_path, [inst(1)])
    afile = alias_file(tmp_path, path, alias())
    rows_only = lambda name, ref: ref == ROWS_REF  # noqa: E731  (both attested the batch, not the alias file)
    [(_, bucket, reason, detail)] = by_sheet(dry_run(path, afile, att=rows_only), "Aliases")
    assert (bucket, reason) == ("skipped", "alias_not_accepted") and load_aliases(afile).attest_ref in detail


def test_an_alias_whose_target_is_not_loaded_rejects_the_rows_that_use_it(tmp_path):
    institutions, facts, programmes = aliased_rows()
    child = inst(5, ctype="exam_calendar", parent_id="T-UNI-X", timezone="Etc/UTC")
    path = workbook(tmp_path, [*institutions, child], facts, programmes)  # T-INST-001 is neither in the file nor stored
    afile = alias_file(tmp_path, path, alias())
    results = dry_run(path, afile)
    assert by_sheet(results, "Programmes") == [("T-PRG-001", "rejected", "alias_target_not_loaded", "T-INST-001")]
    assert by_sheet(results, "Facts") == [("T-F-001", "rejected", "alias_target_not_loaded", "T-INST-001")]
    assert ("T-INST-005", "rejected", "alias_target_not_loaded", "T-INST-001") in by_sheet(results, "Institutions")


def test_a_facts_alias_never_resolves_to_a_programme(tmp_path):
    path = workbook(tmp_path, [inst(1)], [fact(1, "T-UNI-P")], [prog(1, "T-INST-001")])
    afile = alias_file(tmp_path, path, alias(frm="T-UNI-P", to="T-PRG-001"))  # T-PRG-001 is a loaded programme
    results = dry_run(path, afile)
    assert by_sheet(results, "Programmes")[0][1] == "accepted"
    assert by_sheet(results, "Facts") == [("T-F-001", "rejected", "alias_target_not_loaded", "T-PRG-001")]


def test_a_parent_id_naming_an_alias_is_rewritten_to_the_target(tmp_path):
    child = inst(5, ctype="exam_calendar", parent_id="T-UNI-X", timezone="Etc/UTC")
    path = workbook(tmp_path, [inst(1), inst(9, inst_id="T-UNI-X", source_quote=None), child])
    results = dry_run(path, alias_file(tmp_path, path, alias()))
    cal = next(r for r in results if r.sheet == "Institutions" and r.row_id == "T-INST-005")
    assert cal.bucket == "accepted" and cal.payload["entry"].parent_id == TARGET
    assert cal.payload["row"]["parent_id"] == "T-UNI-X" and cal.payload["provenance"]["alias"]["to"] == "T-INST-001"
    without = dry_run(path)
    assert ("T-INST-005", "rejected", "parent_not_loaded", "T-UNI-X") in by_sheet(without, "Institutions")


def test_an_alias_file_is_refused_when_malformed(tmp_path):
    bad = [{"file": "x.xlsx", "aliases": [alias()]},  # no sha256
           {"file": "x.xlsx", "sha256": "ab", "aliases": []},
           {"file": "x.xlsx", "sha256": "ab", "aliases": [{**alias(), "evidence": {"url": "https://a.test/"}}]},
           {"file": "x.xlsx", "sha256": "ab", "aliases": [alias(to="T-UNI-X")]},
           {"file": "x.xlsx", "sha256": "ab", "aliases": [alias(), alias(to="T-INST-002")]}]
    for i, doc in enumerate(bad):
        p = tmp_path / f"bad{i}.yaml"
        p.write_text(yaml.safe_dump(doc), encoding="utf-8")
        with pytest.raises(AliasError):
            load_aliases(p)


def test_unquoted_yaml_yes_is_read_as_yes(tmp_path):
    path = workbook(tmp_path, [inst(1)])
    p = tmp_path / "a.yaml"
    p.write_text(f"file: {path.name}\nsha256: {file_sha256(path)}\naliases:\n  - from: T-UNI-X\n    to: T-INST-001\n"
                 f"    evidence: {{url: '{EVIDENCE['url']}', quote: q}}\n    check1: {{result: correct, name: {A1}}}\n"
                 f"    check2: {{approved: yes, name: {A2}}}\n", encoding="utf-8")
    assert load_aliases(p).aliases[0].checks["checker2_approved"] == "yes"
    assert by_sheet(dry_run(path, p), "Aliases")[0][2] == "alias_applied"


def test_an_alias_file_for_another_file_is_refused_and_nothing_is_imported(engine, clean, tmp_path):
    load_list(engine)
    institutions, facts, programmes = aliased_rows()
    path = workbook(tmp_path, [inst(1), *institutions], facts, programmes)
    wrong = alias_file(tmp_path, path, alias(), sha="0" * 64)
    with pytest.raises(AliasError, match="nothing was imported"):
        imp(path, deps(engine, attested=attested(wrong)), aliases=[wrong])
    assert ImportLog(engine, "pai").list() == [] and RegistryStore(engine, "pai").get(TARGET) is None
    out: list[str] = []
    assert main(["validate", str(path), "--country", COUNTRY, "--aliases", str(wrong)], out=out.append) == 2
    assert out[0].startswith("refused:")


def test_import_against_a_stored_target_with_real_attestations_records_the_alias_and_undo_withdraws_it(
        engine, clean, tmp_path):
    load_list(engine)
    queue = ReviewQueue(engine, "pai", SqlKnowledge(engine, "pai"))
    d = deps(engine, attested=queue.attested)
    first = imp(workbook(tmp_path, [inst(1)], name="first.xlsx"), d)
    institutions, facts, programmes = aliased_rows()
    path = workbook(tmp_path, institutions, facts, programmes, name="second.xlsx")
    afile = alias_file(tmp_path, path, alias())
    af = load_aliases(afile)
    people = ReviewerStore(engine, "pai")
    for ref in (A1, A2):
        queue.attest(people.add(ref, ref, "checker")[0], af.attest_ref)
    res = imp(path, d, aliases=[afile])
    assert res.counts["Institutions"]["skipped"] == 1 and res.counts["Aliases"]["accepted"] == 1
    assert res.counts["Programmes"]["accepted"] == 1 and res.counts["Facts"]["verified"] == 1
    row = fact_row(engine, "deadline_close")
    assert (row.scope, row.ref, row.status) == ("registry", TARGET, "verified")
    used = {"from": "T-UNI-X", "to": "T-INST-001", "evidence": EVIDENCE, "checker1": A1, "checker2": A2}
    assert row.evidence[0]["alias"] == {**used, "alias_file": "aliases.yaml", "alias_sha256": af.sha256,
                                        "attest_ref": af.attest_ref}
    assert fact_row(engine, "seats_open_merit").evidence[0]["alias"]["alias_sha256"] == af.sha256
    assert RegistryStore(engine, "pai").get("inst:t-uni-x") is None  # the aliased row loaded nothing
    rec = ImportLog(engine, "pai").get(res.import_id)
    assert rec.aliases == [{"alias_file": "aliases.yaml", "alias_sha256": af.sha256, "attest_ref": af.attest_ref,
                            "file": "second.xlsx", "file_sha256": file_sha256(path), "applied": [used]}]
    assert record_out(rec)["aliases"] == rec.aliases
    assert ImportLog(engine, "pai").get(first.import_id).aliases == []
    r = undo_import(engine, "pai", res.import_id, actor="admin")
    assert r.facts == 2 and r.programmes == 1
    assert fact_row(engine, "deadline_close").status == "stale" and fact_row(engine, "seats_open_merit").status == "stale"
    assert RegistryStore(engine, "pai").get(TARGET).status == "active"  # the first import's entity stays


def test_the_refetch_waiver_still_applies_with_an_alias_file(engine, clean, tmp_path):
    load_list(engine)
    path = workbook(tmp_path, [inst(1), inst(9, inst_id="T-UNI-X", source_quote=None)],
                    [fact(1, "T-UNI-X", read_method="webfetch (model-extracted)")], name="test-batch.xlsx")
    afile = alias_file(tmp_path, path, alias())
    res = imp(path, deps(engine, attested=attested(afile)), aliases=[afile], fmt=waiver_fmt(path))
    row = fact_row(engine, "deadline_close")
    assert row.status == "verified" and row.read_method == "model" and row.ref == TARGET
    assert row.evidence[0]["refetch_waived"] == "P2 spec §11.3" and row.evidence[0]["alias"]["from"] == "T-UNI-X"
    assert [r.reason for r in res.rows if r.sheet == "Facts"] == ["both_checks"]


def test_the_command_line_takes_alias_files(engine, clean, tmp_path):
    load_list(engine)
    institutions, facts, programmes = aliased_rows()
    path = workbook(tmp_path, [inst(1), *institutions], facts, programmes)
    afile = alias_file(tmp_path, path, alias())
    out: list[str] = []
    base = ["validate", str(path), "--country", COUNTRY, "--no-list-needed", "--aliases", str(afile)]
    assert main(base, out=out.append) == 0 and "Aliases: accepted 0, unconfirmed 0, queued 0, rejected 0, skipped 1" in out
    out.clear()  # the dry run has no review queue: it can show the plan as if the alias checkers had attested
    assert main([*base, "--assume-aliases-attested"], out=out.append) == 0 and "Aliases: accepted 1" in "\n".join(out)
    out.clear()
    assert main(["import", str(path), "--country", COUNTRY, "--owner-accepted", DECISION, "--actor", "dev",
                 "--aliases", str(afile)], deps=deps(engine, attested=attested(afile)), out=out.append) == 0
    assert "Facts: accepted 1" in "\n".join(out)
    assert ImportLog(engine, "pai").list()[0].aliases[0]["alias_file"] == "aliases.yaml"
    out.clear()
    assert main(["list"], deps(engine), out=out.append) == 0 and out[0].endswith("\taliases: aliases.yaml")


@pytest.mark.req("R-68")
def test_os_0034_logs_alias_files_and_goes_back_only_when_no_import_used_one(engine, clean, os_db):
    from sqlalchemy import create_engine

    from tests.os.conftest import run_alembic, truncate_os_tables

    log = ImportLog(engine, "pai")
    plain = log.start(file_name="a.xlsx", sha256="a" * 64, mode="reviewers", decision_ref=None, batch_ref="b",
                      actor="dev")
    assert log.get(plain).aliases == []  # the default
    log.start(file_name="b.xlsx", sha256="b" * 64, mode="reviewers", decision_ref=None, batch_ref="b", actor="dev",
              aliases=[{"alias_file": "x.yaml", "alias_sha256": "c" * 64}])
    engine.dispose()
    with pytest.raises(Exception):
        run_alembic(["downgrade", "os_0033"], os_db)  # an import used an alias file: nothing is thrown away
    eng = create_engine(os_db)
    try:
        truncate_os_tables(eng)
    finally:
        eng.dispose()
    run_alembic(["downgrade", "os_0033"], os_db)
    run_alembic(["upgrade", "os@head"], os_db)

