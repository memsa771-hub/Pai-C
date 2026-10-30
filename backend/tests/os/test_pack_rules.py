"""Slice 6a Task 5: the checklist validator, the data sheet and the instructions, pure functions (spec §2, S6a-D2,
D4, D6, D11). Fictional values only."""

from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.os.knowledge.port import Fact
from app.os.packs.checklist import checklist, complete
from app.os.packs.config import load_pack_configs
from app.os.packs.datasheet import data_sheet
from app.os.packs.inputs import DocState, PackInputs, ProfileValue
from app.os.packs.instructions import fees, instructions
from app.os.playbooks import load_playbook_dir

CFG = load_pack_configs()["germany_master"]
FAKE = load_pack_configs(Path(__file__).parent / "fixtures" / "packs")
BOOK = next(b for (k, _), b in load_playbook_dir().items() if k == "germany_master")
AT = datetime(2026, 10, 22, tzinfo=timezone.utc)
URL = "https://uni.example/apply"


def fact(value, status="confirmed"):
    return Fact(value, "quoted", URL, AT, 2027, status)


def docs_all_confirmed(cfg) -> dict[str, DocState]:
    return {i.ref: DocState(status="confirmed", document_id=n, sha256=f"{n:064x}")
            for n, i in enumerate(cfg.checklist, 1) if i.kind == "document"}


def inputs(cfg=CFG, **over) -> PackInputs:
    base = PackInputs(
        cfg=cfg, documents=docs_all_confirmed(cfg), statements={"sop": "a" * 64, "cv": "b" * 64},
        profile={"passport.surname": ProfileValue("KHAN", "document", 1),
                 "passport.given_names": ProfileValue("SARA AHMED", "document", 1),
                 "entered.email": ProfileValue("sara@example.test", "entered", None)},
        facts={"application_route": fact("uni_assist"), "deadline_close": fact({"date": "2027-07-15"}),
               "tuition_fee_non_eu_eur": fact(1500, "unconfirmed")},
        constants=dict(BOOK.constants), citations={c.source: str(c.url) for t in BOOK.tasks for c in t.citations},
        ticked=set(), added=[], required_override=None)
    return replace(base, **over)


def by_key(results):
    return {r.key: r for r in results}


def test_document_ready_missing_needs_action():
    docs = docs_all_confirmed(CFG)
    docs["passport"] = DocState("read", 1, "1" * 64)  # read, not confirmed yet
    del docs["ielts_trf"]
    docs["transcript"] = DocState("failed", 3, None)
    r = by_key(checklist(inputs(documents=docs), "p1"))
    assert r["passport"].state == "needs_action" and "confirm" in r["passport"].reasons[0]
    assert r["english_test"].state == "missing"
    assert r["transcript"].state == "needs_action" and "clearer copy" in r["transcript"].reasons[0]
    assert r["min_passing_grade"].state == "ready" and r["min_passing_grade"].document_id is not None


def test_format_notes_need_the_students_tick():
    r = by_key(checklist(inputs(), "p1"))
    assert r["degree"].state == "needs_action" and "attested copy" in r["degree"].reasons[0]
    r = by_key(checklist(inputs(ticked={"degree"}), "p1"))
    assert r["degree"].state == "ready" and r["degree"].ticked


def test_unfixable_file_is_needs_action():
    r = by_key(checklist(inputs(ticked={"degree"}), "p1", unfixable={"degree": "too many pages (60); the limit is 40"}))
    assert r["degree"].state == "needs_action" and r["degree"].reasons == ["too many pages (60); the limit is 40"]


def test_statement_needs_approval():
    r = by_key(checklist(inputs(statements={"sop": None, "cv": "b" * 64}), "p1"))
    assert r["sop"].state == "missing" and r["cv"].state == "ready"


def test_programme_sop_when_needed():
    needed = {"sop": "a" * 64, "cv": "b" * 64, "sop:p1": None}
    assert by_key(checklist(inputs(statements=needed), "p1"))["sop"].state == "missing"
    needed["sop:p1"] = "c" * 64
    assert by_key(checklist(inputs(statements=needed), "p1"))["sop"].state == "ready"
    assert by_key(checklist(inputs(statements=needed), "p2"))["sop"].state == "ready"  # p2 uses the base SOP


def test_research_overrides_default():
    r = checklist(inputs(required_override=["passport", "transcript", "sop"]), "p1")
    keys = [x.key for x in r]
    assert keys == ["passport", "transcript", "sop", "fee_paid"]  # manual items always stay
    assert {x.source for x in r if x.kind != "manual"} == {"research"}
    assert by_key(checklist(inputs(), "p1"))["passport"].source == "default"


def test_student_added_item_is_manual():
    r = by_key(checklist(inputs(added=[("added:1", "Module descriptions")], ticked={"added:1"}), "p1"))
    item = r["added:1"]
    assert (item.label, item.kind, item.state, item.ticked, item.source) == (
        "Module descriptions", "manual", "manual", True, "student")


def test_manual_needs_tick_and_complete():
    ready = inputs(ticked={"degree", "transcript", "hssc", "ssc"}, added=[("added:1", "Module descriptions")])
    assert not complete(checklist(ready, "p1"))  # the student's own item not ticked
    assert complete(checklist(replace(ready, ticked=ready.ticked | {"added:1"}), "p1"))
    # fee_paid is ticked after approving (Slice 9 Task 11): it never blocks approval


def test_sheet_values_and_gaps():
    rows = {r.key: r for r in data_sheet(inputs())}
    assert (rows["surname"].value, rows["surname"].source, rows["surname"].document_id) == ("KHAN", "document", 1)
    assert rows["passport_number"].value is None and rows["passport_number"].gap  # required, missing
    assert rows["postcode"].value is None and not rows["postcode"].gap  # optional
    assert [r.section for r in data_sheet(inputs())][0] == "Personal details"


def test_entered_value_named_entered():
    rows = {r.key: r for r in data_sheet(inputs())}
    assert (rows["email"].value, rows["email"].source, rows["email"].document_id) == ("sara@example.test",
                                                                                       "entered", None)


def test_instructions_filled_with_sources():
    route, steps = instructions(inputs(), "p1")
    assert route == "uni_assist" and [s.n for s in steps] == [1, 2, 3, 4]
    assert "2027-07-15" in steps[3].text and steps[3].unconfirmed == []
    assert steps[0].source_url == "https://www.uni-assist.de/en/faqs/apply-online/"  # citation S6
    route, steps = instructions(inputs(facts={"application_route": fact("direct")}), "p1")
    assert route == "direct" and "not confirmed yet" in steps[2].text and steps[2].unconfirmed == ["deadline_close"]


def test_unconfirmed_route_no_guess():
    for facts in ({}, {"application_route": fact("uni_assist", "unconfirmed")}):
        route, steps = instructions(inputs(facts=facts), "p1")
        assert route is None and len(steps) == 1
        assert "not confirmed yet" in steps[0].text and steps[0].unconfirmed == ["application_route"]
    assert instructions(inputs(facts={"application_route": fact("uni_assist", "unconfirmed")}), "p1")[1][0].source_url == URL


def test_fees_show_status_and_source():
    rows = {r.label: r for r in fees(inputs())}
    handling = rows["uni-assist handling fee (first programme)"]
    assert (handling.value, handling.status) == ("75", "confirmed") and handling.source_url.startswith("https://www.uni-assist")
    assert (rows["Tuition per semester (non-EU)"].value, rows["Tuition per semester (non-EU)"].status) == ("1500", "unconfirmed")
    assert rows["Semester contribution"].value is None and rows["Semester contribution"].status == "missing"


def test_fake_routes_build_sheet_and_checklist():
    for route, cfg in FAKE.items():
        inp = inputs(cfg=cfg, constants={}, citations={}, facts={"application_route": fact(next(iter(cfg.instructions)))})
        assert data_sheet(inp) and checklist(inp, "p1")
        assert instructions(inp, "p1")[0] == next(iter(cfg.instructions)), route
    ireland = by_key(checklist(inputs(cfg=FAKE["ireland_master"], constants={}, citations={}), "p1"))
    assert ireland["referee"].state == "missing"  # an entered item with no value yet
    with_referee = inputs(cfg=FAKE["ireland_master"], constants={}, citations={},
                          profile={"entered.referee_name": ProfileValue("Dr Example", "entered", None)})
    assert by_key(checklist(with_referee, "p1"))["referee"].state == "ready"


def test_rows_say_which_fields_the_student_types():
    rows = {r.key: r for r in data_sheet(inputs())}
    assert rows["email"].entered and rows["phone"].entered and not rows["surname"].entered


def test_items_say_whether_a_tick_settles_them():
    r = by_key(checklist(inputs(added=[("added:1", "Module descriptions")]), "p1"))
    assert r["degree"].tickable and r["fee_paid"].tickable and r["added:1"].tickable  # attested note, manual, added
    assert not r["passport"].tickable and not r["sop"].tickable
    docs = docs_all_confirmed(CFG)
    docs["degree_certificate"] = DocState("failed", 2, None)
    assert not by_key(checklist(inputs(documents=docs), "p1"))["degree"].tickable  # a tick can't fix a bad scan
