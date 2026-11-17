"""P2-T6: what happens to each row: the status mapping, the owner-accepted rules of the v4 README and the validation
reasons (P2 spec §4.6, P2-D16, P2-D16a; master R-68, R-72, R-76). Pure: no database."""

import pytest

from app.os.knowledge.sheets.importer import plan_file
from app.os.knowledge.sheets.plan import (
    REVIEWERS,
    Checks,
    PlanContext,
    decide,
    read_checks,
    summarise,
)
from tests.os.registry.helpers import LIST_URL

from .helpers import C1, C2, COUNTRY, checks, fact, inst, prog, waiver_fmt, workbook

pytestmark = pytest.mark.req("R-68")
LISTS = {LIST_URL.lower(): "list:alpha-list"}


def ctx(**kw) -> PlanContext:
    return PlanContext(country=COUNTRY, list_urls=dict(LISTS), **kw)


def plan(tmp_path, institutions=(), facts=(), programmes=(), waiver=False, **kw):
    """`waiver=True`: the file is one the §11.3 waiver covers (the real five are not ours), with a decision reference."""
    path = workbook(tmp_path, institutions, facts, programmes)
    if waiver:
        kw["fmt"] = waiver_fmt(path)
        kw.setdefault("decision_ref", "chat 2026-11-07")
    _, results = plan_file(path, ctx(**kw))
    return {(r.sheet, r.row_id): r for r in results}


@pytest.mark.parametrize("status,c1,c2,hs,expect", [
    ("found", "correct", "yes", True, ("accepted", "verified", None)),
    ("unconfirmed", "correct", "yes", True, ("accepted", "verified", None)),  # README v4: accepted by both checks
    ("found", "correct", None, True, ("accepted", "confirmed", None)),  # high-stakes without check 2: never verified
    ("found", "correct", None, False, ("accepted", "confirmed", None)),
    ("found", "correct", "no", True, ("queued", None, "import_dispute")),
    ("found", "wrong", "yes", True, ("queued", None, "import_dispute")),
    ("found", "unclear", None, True, ("unconfirmed", "unconfirmed", None)),
    ("found", None, None, True, ("unconfirmed", "unconfirmed", None)),
    ("conflict", "correct", "yes", True, ("unconfirmed", "unconfirmed", "conflict")),
    ("unconfirmed", "unclear", None, True, ("unconfirmed", "unconfirmed", None)),
    ("not_readable", "correct", "yes", True, ("queued", None, "collect")),
    ("found", "not_readable", None, True, ("unconfirmed", "unconfirmed", None)),  # README v4: check 1 not_readable
    ("not_found", "correct", "yes", True, ("skipped", None, None)),
    ("lead_only", "correct", "yes", True, ("skipped", None, None)),
    ("superseded", "correct", "yes", True, ("skipped", None, None)),
])
def test_status_mapping(status, c1, c2, hs, expect):
    bucket, level, _, kind = decide(status, Checks(c1, c2, [], {}), hs)
    assert (bucket, level, kind) == expect


def test_owner_accepted_mode_takes_only_the_two_ai_checks(tmp_path):
    rows = plan(tmp_path, [inst(1), inst(2, chk=checks(n2="Some Person")), inst(3, chk=checks(n1="Some Person"))])
    assert rows[("Institutions", "T-INST-001")].level == "verified"
    assert rows[("Institutions", "T-INST-002")].level == "confirmed"  # check 2 is not an accepted check
    assert rows[("Institutions", "T-INST-003")].level == "unconfirmed"  # nor is check 1
    assert "not a check the owner accepted" in rows[("Institutions", "T-INST-003")].detail
    assert rows[("Institutions", "T-INST-001")].payload["provenance"] == {
        "checker1": "claude_check_1", "checker2": "claude_check_2", "checker1_name": C1, "checker2_name": C2}


def test_reviewer_mode_needs_attested_different_reviewers():
    attested = {("amina", "b1"), ("bilal", "b1")}
    c = PlanContext(country=COUNTRY, mode=REVIEWERS, batch_ref="b1", attested=lambda r, b: (r, b) in attested)
    ok = read_checks({"checker1_result": "correct", "checker1_name": "amina", "checker2_approved": "yes",
                      "checker2_name": "bilal"}, c)
    assert (ok.c1, ok.c2) == ("correct", "yes")
    same = read_checks({"checker1_result": "correct", "checker1_name": "amina", "checker2_approved": "yes",
                        "checker2_name": "amina"}, c)
    assert (same.c1, same.c2) == ("correct", None)
    unknown = read_checks({"checker1_result": "correct", "checker1_name": "zed", "checker2_approved": "yes",
                           "checker2_name": "bilal"}, c)
    assert (unknown.c1, unknown.c2) == (None, "yes") and "has not attested" in unknown.notes[0]
    nobody = read_checks({"checker1_result": "correct", "checker1_name": "amina"},
                         PlanContext(country=COUNTRY, mode=REVIEWERS, batch_ref="b1"))
    assert nobody.c1 is None  # no attestation source: nothing counts


def test_institution_validation_reasons(tmp_path):
    rows = plan(tmp_path, [
        inst(1), inst(2, region="Narnia"), inst(3, ctype="moon_base"), inst(4, source_quote=None),
        inst(5, source_url="https://nowhere.alpha.test/x"), inst(6, source_url="https://en.wikipedia.org/wiki/X"),
        inst(7, retrieved="soon"), inst(8, read_method="a guess"), inst(9, in_scope="no"), inst(10, status="lead_only"),
        inst(11, status="not_found"), inst(12, status="mystery"), inst(1, name="again"),
        inst(13, ctype="examination_board", source_url="http://insecure.alpha.test/x"),
    ])
    reason = {k[1]: v.reason for k, v in rows.items()}
    assert reason["T-INST-001"] in ("duplicate_id",)  # the second T-INST-001 replaces the first in the dict
    assert reason["T-INST-002"] == "unknown_region" and rows[("Institutions", "T-INST-002")].bucket == "rejected"
    assert reason["T-INST-003"] == "unknown_type"
    assert reason["T-INST-004"] == "no_quote"
    assert reason["T-INST-005"] == "no_official_list"
    assert reason["T-INST-006"] == "non_official_source"
    assert reason["T-INST-007"] == "bad_date"
    assert reason["T-INST-008"] == "unknown_read_method"
    assert (reason["T-INST-009"], rows[("Institutions", "T-INST-009")].bucket) == ("out_of_scope", "skipped")
    assert reason["T-INST-010"] == "lead" and reason["T-INST-011"] == "searched"
    assert reason["T-INST-012"] == "bad_status"
    assert reason["T-INST-013"] == "invalid_entry"  # the registry takes https sources only (T2)


def test_a_missing_id_and_a_duplicate_are_rejected_not_dropped(tmp_path):
    _, results = plan_file(workbook(tmp_path, [inst(1), inst(1), {**inst(2), "inst_id": None}]), ctx())
    assert [r.reason for r in results] == ["both_checks", "duplicate_id", "missing_id"]
    assert [r.src_row for r in results] == [2, 3, 4]


def test_a_non_institution_kind_needs_no_official_list_but_a_region(tmp_path):
    rows = plan(tmp_path, [inst(1, ctype="examination_board", source_url="https://board.alpha.test/members"),
                           inst(2, ctype="examination_board", region=None)])
    assert rows[("Institutions", "T-INST-001")].bucket == "accepted"
    assert rows[("Institutions", "T-INST-002")].reason == "missing_region"


def test_reviewers_mode_keeps_the_refetch_for_model_read_rows(tmp_path):
    c = PlanContext(country=COUNTRY, mode=REVIEWERS, batch_ref="b", attested=lambda r, b: True, list_urls=dict(LISTS))
    ok = checks(n1="amina", n2="bilal")
    _, results = plan_file(workbook(tmp_path, [inst(1, chk=ok)], [
        fact(1, "T-INST-001", chk=ok, read_method="webfetch (model-extracted)"), fact(2, "T-INST-001", field_="b", chk=ok)]),
        c)
    f1, f2 = [r for r in results if r.sheet == "Facts"]
    assert f1.needs_refetch and "refetch_waived" not in f1.payload["provenance"] and not f2.needs_refetch


def test_a_single_check_model_read_row_keeps_the_refetch_even_in_owner_mode(tmp_path):
    rows = plan(tmp_path, [inst(1)], [fact(1, "T-INST-001", read_method="image (machine-read)", chk=checks("correct", None))])
    r = rows[("Facts", "T-F-001")]
    assert r.level == "confirmed" and r.needs_refetch


def test_foreign_rows_and_what_hangs_on_them_are_skipped_not_rejected(tmp_path):
    rows = plan(tmp_path, [inst(1), inst(2, ctype="foreign_qualification_awarding_body", region="United Kingdom"),
                           inst(3, ctype="foreign_qualification_awarding_body", region="australia")],
                [fact(1, "T-INST-002"), fact(2, "T-INST-001", field_="x")],
                [prog(1, "T-INST-003")])
    assert rows[("Institutions", "T-INST-002")].reason == "out_of_scope_region"
    assert rows[("Institutions", "T-INST-003")].bucket == "skipped"
    assert (rows[("Facts", "T-F-001")].bucket, rows[("Facts", "T-F-001")].reason) == ("skipped", "entity_out_of_scope")
    assert rows[("Facts", "T-F-002")].bucket == "accepted"
    assert (rows[("Programmes", "T-PRG-001")].bucket, rows[("Programmes", "T-PRG-001")].reason) == (
        "skipped", "entity_out_of_scope")


def test_the_allow_list_check_caps_a_row_at_unconfirmed(tmp_path):
    rows = plan(tmp_path, [inst(1)], official=lambda url, scope: False)
    r = rows[("Institutions", "T-INST-001")]
    assert (r.bucket, r.level, r.reason) == ("unconfirmed", "unconfirmed", "source_not_on_allow_list")
    seen = []
    plan(tmp_path, [inst(1)], official=lambda url, scope: seen.append(scope) or True, family="intermediate")
    assert seen[0].region == "punjab" and seen[0].family == "intermediate"


def test_fact_rows_become_buckets_with_reasons(tmp_path):
    e = "T-INST-001"
    rows = plan(tmp_path, [inst(1)], [
        fact(1, e), fact(2, e, field_="a", chk=checks("unclear", None)), fact(3, e, field_="b", intake="whenever"),
        fact(4, "T-INST-*", field_="c"), fact(5, "T-NOBODY", field_="d"), fact(6, e, field_="e", value=None),
        fact(7, e, field_="f", status="not_readable"), fact(8, e, field_="g", status="conflict"),
        fact(9, e, field_="h", quote_verbatim=None), fact(10, e), fact(11, e, field_="i", source_type="social"),
        fact(12, e, field_="j", read_method="webfetch (model-extracted)"), fact(13, e, field_="k", language="Urdu"),
        fact(14, e, field_="l", chk=checks("correct", "no")),
    ], waiver=True)
    got = {k[1]: (v.bucket, v.reason) for k, v in rows.items() if k[0] == "Facts"}
    assert got["T-F-001"] == ("accepted", "both_checks")
    assert got["T-F-002"] == ("unconfirmed", "check_unclear_or_missing")
    assert got["T-F-003"] == ("queued", "intake_unresolved")
    assert got["T-F-004"] == ("rejected", "entity_not_single")
    assert got["T-F-005"] == ("rejected", "entity_unknown")
    assert got["T-F-006"] == ("rejected", "no_value")
    assert got["T-F-007"] == ("queued", "not_readable") and rows[("Facts", "T-F-007")].queue_kind == "collect"
    assert got["T-F-008"] == ("unconfirmed", "conflict")
    assert got["T-F-009"] == ("unconfirmed", "no_quote")  # no quote: never above unconfirmed
    assert got["T-F-010"] == ("rejected", "duplicate_key")
    assert got["T-F-011"] == ("rejected", "non_official_source")
    assert got["T-F-012"] == ("accepted", "both_checks")
    # owner ruling §11.3: both AI checks accepted a model-read row, so no re-fetch, and the waiver is on the record
    assert not rows[("Facts", "T-F-012")].needs_refetch
    assert rows[("Facts", "T-F-012")].payload["provenance"]["refetch_waived"] == "P2 spec §11.3"
    assert "refetch_waived" not in rows[("Facts", "T-F-001")].payload["provenance"]
    assert got["T-F-013"] == ("rejected", "bad_language")
    assert got["T-F-014"] == ("queued", "checker2_rejected")
    assert rows[("Facts", "T-F-001")].payload["term"] == "fall" and rows[("Facts", "T-F-001")].payload["year"] == 2027


@pytest.mark.parametrize("text,expect", [
    ("Fall 2027", ("fall", 2027)), ("Fall 2026 (Second)", ("fall", 2026)), ("Session 2026-27", ("session", 2026)),
    ("2026-27", ("session", 2026)), ("2026-27 (undated)", ("session", 2026)), ("2026", ("", 2026)),
    ("Batch 2026", ("batch", 2026)), ("standing", None), ("previous cycle (as shown on 2026-11-03)", None),
    ("current", None), (None, None),
])
def test_intake_text_to_term_and_year(text, expect):
    from app.os.knowledge.sheets.format import load_format
    assert load_format().intake(text) == expect


def test_programme_rows_make_facts_per_value_column(tmp_path):
    rows = plan(tmp_path, [inst(1)], programmes=[
        prog(1, "T-INST-001", closing_merit="88.5", closing_scale="100", min_hssc="60%"),
        prog(2, "T-INST-NOPE"), prog(3, "T-INST-001", intake="whenever"),
        prog(4, "T-INST-001", seat_category=None, seats=None, test_options="Alpha test")])
    p1 = rows[("Programmes", "T-PRG-001")]
    assert p1.bucket == "accepted" and p1.level == "verified"
    fields = {f["field"]: (f["fact_class"], f["value"]) for f in p1.payload["facts"]}
    assert fields == {"seats_open_merit": ("seat_quota", {"value": "100"}),
                      "closing_merit_open_merit": ("closing_merit", {"value": "88.5", "scale": "100"}),
                      "min_hssc": ("eligibility_threshold", {"value": "60%"})}
    assert rows[("Programmes", "T-PRG-002")].reason == "institution_not_loaded"
    assert (rows[("Programmes", "T-PRG-003")].bucket, rows[("Programmes", "T-PRG-003")].reason) == (
        "queued", "intake_unresolved")
    assert [f["field"] for f in rows[("Programmes", "T-PRG-004")].payload["facts"]] == ["test_options"]


def test_summary_counts(tmp_path):
    _, results = plan_file(workbook(tmp_path, [inst(1), inst(2, region="Narnia")], [fact(1, "T-INST-001")]), ctx())
    s = summarise(results)
    assert s["Institutions"]["accepted"] == 1 and s["Institutions"]["rejected"] == 1 and s["Institutions"]["verified"] == 1
    assert s["Facts"]["accepted"] == 1


def test_the_waiver_needs_a_listed_file_and_a_decision_reference(tmp_path):
    model = {"read_method": "webfetch (model-extracted)"}
    cases = {
        "other file": plan(tmp_path, [inst(1)], [fact(1, "T-INST-001", **model)]),
        "no decision": plan(tmp_path, [inst(1)], [fact(1, "T-INST-001", **model)], waiver=True, decision_ref=""),
    }
    for name, rows in cases.items():
        r = rows[("Facts", "T-F-001")]
        assert r.needs_refetch and "refetch_waived" not in r.payload["provenance"], name
    ok = plan(tmp_path, [inst(1)], [fact(1, "T-INST-001", **model)], waiver=True)[("Facts", "T-F-001")]
    assert not ok.needs_refetch and ok.payload["provenance"]["refetch_waived"] == "P2 spec §11.3"


def test_the_five_real_v4_files_are_the_listed_ones():
    from app.os.knowledge.sheets.format import load_format

    files = load_format().raw["owner_accepted"]["refetch_waiver"]["files"]
    assert sorted(files) == [f"PAI-Research-Batch{n}-{name}-v4.xlsx" for n, name in (
        (1, "National"), (2, "Punjab"), (3, "Sindh"), (4, "KP-Bal-ICT-AJK-GB"), (5, "Universities-BS"))]
    assert all(len(h) == 64 for h in files.values())


def test_a_missing_read_method_is_never_assumed_to_be_fetch(tmp_path):
    rows = plan(tmp_path, [inst(1)], programmes=[prog(1, "T-INST-001", read_method=None)])
    r = rows[("Programmes", "T-PRG-001")]
    assert r.bucket == "accepted" and r.needs_refetch and r.payload["read_method"] is None
    waived = plan(tmp_path, [inst(1)], programmes=[prog(1, "T-INST-001", read_method=None)], waiver=True)
    w = waived[("Programmes", "T-PRG-001")]
    assert not w.needs_refetch and w.payload["provenance"]["refetch_waived"] == "P2 spec §11.3"
    single = plan(tmp_path, [inst(1)], programmes=[prog(1, "T-INST-001", read_method=None, **checks("correct", None))],
                  waiver=True)
    assert single[("Programmes", "T-PRG-001")].needs_refetch  # only rows both AI checks accepted are waived


def test_a_fact_attaches_only_to_a_programme_that_was_loaded(tmp_path):
    rows = plan(tmp_path, [inst(1)], [
        fact(1, "T-PRG-001", field_="a"),  # loaded
        fact(2, "T-PRG-002", field_="b"),  # its row was queued (intake unresolved)
        fact(3, "T-PRG-003", field_="c"),  # its row was rejected (institution unknown)
        fact(4, "T-PRG-009", field_="d"),  # nowhere
    ], [prog(1, "T-INST-001"), prog(2, "T-INST-001", intake="whenever"), prog(3, "T-INST-404")])
    got = {k[1]: v.reason for k, v in rows.items() if k[0] == "Facts"}
    assert got == {"T-F-001": "both_checks", "T-F-002": "programme_not_loaded", "T-F-003": "programme_not_loaded",
                   "T-F-004": "entity_unknown"}
    existing = plan(tmp_path, [inst(1)], [fact(1, "T-PRG-777", field_="a")], existing_programmes=lambda ref: True)
    assert existing[("Facts", "T-F-001")].reason == "both_checks"  # a programme that already exists is fine


def test_a_programme_row_with_no_value_column_is_rejected(tmp_path):
    rows = plan(tmp_path, [inst(1)], programmes=[prog(1, "T-INST-001", seats=None, seat_category=None)])
    assert rows[("Programmes", "T-PRG-001")].reason == "no_value"


def test_a_rejected_row_does_not_shadow_a_later_valid_one(tmp_path):
    rows = plan(tmp_path, [inst(1)], [fact(1, "T-INST-001", language="Urdu"), fact(2, "T-INST-001")])
    assert rows[("Facts", "T-F-001")].reason == "bad_language" and rows[("Facts", "T-F-002")].bucket == "accepted"


# --- official calendars: rows and dates (P2-T11) ----------------------------------------------------------------------


def calendar_rows(**kw):
    body = inst(1, ctype="admission_body", source_url="https://board.alpha.test/about", timezone="Asia/Karachi")
    cal = inst(2, ctype="result_calendar", source_url="https://board.alpha.test/results", parent_id="T-INST-001", **kw)
    return [body, cal]


def test_a_calendar_row_has_its_kind_type_parent_and_zone(tmp_path):
    rows = plan(tmp_path, calendar_rows())
    cal = rows[("Institutions", "T-INST-002")]
    assert cal.bucket == "accepted" and cal.payload["kind"] == "calendar" and cal.payload["calendar_type"] == "result"
    assert cal.payload["entry"].entity_id == "cal:t-inst-002" and cal.payload["entry"].parent_id == "body:t-inst-001"
    assert rows[("Institutions", "T-INST-001")].payload["timezone"] == "Asia/Karachi"
    gone = plan(tmp_path, [calendar_rows()[1]])  # its parent is not loaded
    assert gone[("Institutions", "T-INST-002")].reason == "parent_not_loaded"
    assert plan(tmp_path, calendar_rows(timezone="Mars/Base"))[("Institutions", "T-INST-002")].reason == "bad_timezone"


def test_a_date_of_a_calendar_is_checked_against_the_calendars_type_and_gets_a_zone(tmp_path):
    cal = "T-INST-002"
    rows = plan(tmp_path, calendar_rows(), [
        fact(1, cal, field_="result_date", value="2031-05-20", intake="Fall 2031"),
        fact(2, cal, field_="exam_date", value="2031-05-20", intake="Fall 2031"),  # a result calendar has no exam date
        fact(3, cal, field_="result_date", value="20 May", intake="Fall 2032"),
        fact(4, cal, field_="result_date", value="2031-05-20", intake="Fall 2033", unit="date"),
    ])
    ok = rows[("Facts", "T-F-001")]
    assert ok.bucket == "accepted" and ok.payload["value"] == {"date": "2031-05-20", "tz": "Asia/Karachi"}  # the parent's
    assert ok.payload["calendar"] == "schedule_date"
    assert rows[("Facts", "T-F-002")].reason == "field_not_in_calendar"
    assert rows[("Facts", "T-F-003")].reason == "not_a_date"
    assert rows[("Facts", "T-F-004")].bucket == "accepted"


def test_a_calendars_own_zone_wins_and_no_zone_anywhere_is_refused(tmp_path):
    own = plan(tmp_path, calendar_rows(timezone="Etc/UTC"), [fact(1, "T-INST-002", field_="result_date",
                                                                  value="2031-05-20", intake="Fall 2031")])
    assert own[("Facts", "T-F-001")].payload["value"]["tz"] == "Etc/UTC"
    body = inst(1, ctype="admission_body", source_url="https://board.alpha.test/about")  # no zone on the body either
    cal = inst(2, ctype="result_calendar", source_url="https://board.alpha.test/results", parent_id="T-INST-001")
    none = plan(tmp_path, [body, cal], [fact(1, "T-INST-002", field_="result_date", value="2031-05-20",
                                             intake="Fall 2031")])
    assert none[("Facts", "T-F-001")].reason == "no_timezone"


def test_facts_about_other_entities_are_untouched_by_the_calendar_rules(tmp_path):
    rows = plan(tmp_path, calendar_rows(), [fact(1, "T-INST-001", field_="exam_date", value="whenever",
                                                 intake="Fall 2031")])
    assert rows[("Facts", "T-F-001")].bucket == "accepted"  # the body is not a calendar: its value is kept as given
    assert rows[("Facts", "T-F-001")].payload["value"] == {"value": "whenever", "unit": "date"}
