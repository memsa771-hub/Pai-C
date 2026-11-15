"""P3-T3 (ADR-001 D3; master R-38): a system's admission mode enters through the import. The value must be a mode of
`registry/admission_modes.yaml` and the fact may sit only on an `admission_system` entity; anything else is rejected
with its reason. Fictional bodies on `.test` domains."""

import pytest

from app.os.knowledge.sheets.importer import build_context, plan_file, run_import

from .helpers import COUNTRY, deps, fact, inst, load_list, prog, workbook

pytestmark = pytest.mark.req("R-38")
SYS = "sys:alpha-admissions"


def rows():
    body = inst(1, ctype="admission_body", source_url="https://board.alpha.test/about", timezone="Asia/Karachi")
    body.update(inst_id="ALPHA-BODY", name="Alpha admission body")
    system = inst(2, ctype="admission_system", source_url="https://apply.alpha.test/", parent_id="ALPHA-BODY")
    system.update(inst_id="ALPHA-ADMISSIONS", name="Alpha admission system")
    college = inst(3)
    return [body, system, college]


def mode_fact(n, entity, value="central_portal", **kw):
    return fact(n, entity, field_="admission_mode", value=value, unit=None, intake="Session 2027-28",
                high_stakes="N", quote_verbatim="Apply online through the one portal", **kw)


def dry_ctx():
    return build_context(None, country=COUNTRY, mode="owner_accepted", batch_ref="b", family="", require_list=False,
                         decision_ref="ref-1")


def facts_of(results):
    return {r.row_id: r for r in results if r.sheet == "Facts"}


def test_a_valid_mode_on_a_system_is_accepted_as_the_bare_mode_key(tmp_path):
    path = workbook(tmp_path, rows(), [mode_fact(1, "ALPHA-ADMISSIONS")])
    r = facts_of(plan_file(path, dry_ctx())[1])["T-F-001"]
    assert (r.bucket, r.reason) == ("accepted", "both_checks")
    assert (r.payload["scope"], r.payload["ref"], r.payload["value"]) == ("registry", SYS, "central_portal")


@pytest.mark.parametrize("entity, value, reason, words", [
    ("ALPHA-ADMISSIONS", "lottery", "unknown_admission_mode", ["'lottery'", "central_ranked"]),
    ("ALPHA-ADMISSIONS", "Central Portal", "unknown_admission_mode", ["'Central Portal'"]),
    ("ALPHA-BODY", "central_portal", "mode_on_wrong_kind", ["admission_system", "admission_body"]),
    ("T-INST-003", "central_portal", "mode_on_wrong_kind", ["admission_system", "institution"]),
])
def test_a_bad_mode_or_a_wrong_kind_is_rejected_with_its_reason(tmp_path, entity, value, reason, words):
    path = workbook(tmp_path, rows(), [mode_fact(1, entity, value)])
    r = facts_of(plan_file(path, dry_ctx())[1])["T-F-001"]
    assert (r.bucket, r.reason) == ("rejected", reason)
    assert all(w in r.detail for w in words), r.detail


def test_a_mode_on_a_programme_is_rejected(tmp_path):
    path = workbook(tmp_path, rows(), [mode_fact(1, "T-PRG-001")], [prog(1, "T-INST-003")])
    r = facts_of(plan_file(path, dry_ctx())[1])["T-F-001"]
    assert (r.bucket, r.reason) == ("rejected", "mode_on_wrong_kind")
    assert "programme" in r.detail


def test_the_mode_is_stored_on_the_system_and_a_wrong_one_is_not(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    facts = [mode_fact(1, "ALPHA-ADMISSIONS"), mode_fact(2, "ALPHA-BODY")]
    res = run_import(workbook(tmp_path, rows(), facts), d, mode="owner_accepted", actor="dev", country=COUNTRY,
                     decision_ref="ref-1")
    got = facts_of(res.rows)
    assert (got["T-F-001"].bucket, got["T-F-002"].bucket) == ("accepted", "rejected")
    stored = d.knowledge.registry_facts([SYS, "body:alpha-body"], ["admission_mode"], 2027, intake_term="session")
    f = stored[(SYS, "admission_mode")]
    assert f.value == "central_portal" and f.status == "verified" and f.intake_term == "session"
    assert ("body:alpha-body", "admission_mode") not in stored


def test_a_stored_system_is_judged_by_its_stored_kind(engine, clean, tmp_path):
    load_list(engine)
    d = deps(engine)
    run_import(workbook(tmp_path, rows(), [], name="first.xlsx"), d, mode="owner_accepted", actor="dev",
               country=COUNTRY, decision_ref="ref-1")
    res = run_import(workbook(tmp_path, [], [mode_fact(1, "ALPHA-ADMISSIONS"), mode_fact(2, "ALPHA-BODY")],
                              name="second.xlsx"), d, mode="owner_accepted", actor="dev", country=COUNTRY,
                     decision_ref="ref-1")
    got = facts_of(res.rows)
    assert (got["T-F-001"].bucket, got["T-F-001"].reason) == ("accepted", "both_checks")
    assert (got["T-F-002"].bucket, got["T-F-002"].reason) == ("rejected", "mode_on_wrong_kind")
