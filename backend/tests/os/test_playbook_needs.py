"""P1-T8 Task 1: playbook `needs` and `asks`, the v2 playbooks, selection through the needs gate. Fictional data."""

import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.os.compiler import needed_fields
from app.os.knowledge import SqlKnowledge, load_seed
from app.os.playbooks import (
    PLAYBOOK_DIR, PlaybookError, load_playbook, load_playbook_dir, newest_plain, select_playbook,
)
from app.os.playbooks.models import REQUEST_TEMPLATES, Need
from app.os.runner import default_registry

HERE = Path(__file__).parent
FAKE_DIR = HERE / "playbooks"
NEEDS_DIR = FAKE_DIR / "needs"
IE = FAKE_DIR / "ireland_master.v1.yaml"
SEED = HERE / "fixtures" / "needs_seed.yaml"

pytestmark = pytest.mark.req("R-18")


def _write(tmp_path: Path, data: dict, name: str = "pb.v2.yaml") -> Path:
    p = tmp_path / name
    p.write_text(yaml.safe_dump(data, sort_keys=False))
    return p


def _ie_needs() -> dict:
    d = yaml.safe_load(IE.read_text())
    d["version"] = 2
    d["tasks"][0]["needs"] = [{"fact": "education.matric.marks_obtained", "evidence": "stated"}]
    d["asks"] = {"education.matric.marks_obtained": {
        "stated": "Tell us your marks", "which_is_right": "Which marks are right?"}}
    return d


def _load(tmp_path, data):
    return load_playbook(_write(tmp_path, data))


def test_valid_needs_load(tmp_path):
    book = _load(tmp_path, _ie_needs())
    assert book.declares_needs
    assert book.tasks[0].needs[0].fact == "education.matric.marks_obtained"


@pytest.mark.parametrize("kwargs", [
    {"evidence": "stated"},
    {"fact": "a.b", "document": "passport", "evidence": "shown"},
])
def test_need_needs_one_of_fact_or_document(kwargs):
    with pytest.raises(ValidationError, match="exactly one of"):
        Need(**kwargs)


def test_need_needs_an_evidence_level():
    with pytest.raises(ValidationError):
        Need(fact="a.b")


def test_every_need_has_an_ask_title_for_its_level(tmp_path):
    d = _ie_needs()
    d["tasks"][0]["needs"][0]["evidence"] = "shown"  # asks only has `stated`
    with pytest.raises(PlaybookError, match="no 'shown' title"):
        _load(tmp_path, d)
    d = _ie_needs()
    d["asks"] = {}
    with pytest.raises(PlaybookError, match="no entry in 'asks'"):
        _load(tmp_path, d)


def test_fact_need_needs_a_which_is_right_title(tmp_path):
    d = _ie_needs()
    del d["asks"]["education.matric.marks_obtained"]["which_is_right"]
    with pytest.raises(PlaybookError, match="which_is_right"):
        _load(tmp_path, d)


@pytest.mark.parametrize("level,ok", [("shown", True), ("stated", False), ("confirmed", False)])
def test_document_need_accepts_shown_only(tmp_path, level, ok):
    d = _ie_needs()
    d["tasks"][0]["needs"] = [{"document": "transcript", "evidence": level}]
    d["asks"] = {"transcript": {level: "Upload your transcript"}}
    if ok:
        assert _load(tmp_path, d).declares_needs
    else:
        with pytest.raises(PlaybookError, match="document need.*shown"):
            _load(tmp_path, d)


def test_expected_only_on_a_fact_ask(tmp_path):
    d = _ie_needs()
    d["tasks"][0]["needs"] = [{"document": "transcript", "evidence": "shown"}]
    d["asks"] = {"transcript": {"shown": "Upload it", "expected": {"fact": "result_date", "title": "Result expected"}}}
    with pytest.raises(PlaybookError, match="expected"):
        _load(tmp_path, d)
    d = _ie_needs()
    d["asks"]["education.matric.marks_obtained"]["expected"] = {"fact": "result_date", "title": "Result expected"}
    assert _load(tmp_path, d).asks["education.matric.marks_obtained"].expected.fact == "result_date"


@pytest.mark.parametrize("key", REQUEST_TEMPLATES)
def test_reserved_template_keys_refused(tmp_path, key):
    d = _ie_needs()
    d["tasks"][1]["template_key"] = key
    d["tasks"] = [d["tasks"][0], {**d["tasks"][1], "depends_on": []}]
    with pytest.raises(PlaybookError, match="reserved"):
        _load(tmp_path, d)


def test_need_on_a_fan_out_step_is_allowed(tmp_path):
    d = _ie_needs()
    d["tasks"][0]["needs"].append({"fact": "education.matric.marks_total", "evidence": "stated"})
    d["asks"]["education.matric.marks_total"] = {"stated": "Tell us the total", "which_is_right": "Which total?"}
    assert d["tasks"][0]["fan_out"] == "programme"
    assert len(_load(tmp_path, d).tasks[0].needs) == 2


# ---- the v2 playbooks ----------------------------------------------------------------------------

def test_germany_v2_loads_and_differs_from_v1_only_in_needs():
    books = load_playbook_dir(PLAYBOOK_DIR)
    v1, v2 = books[("germany_master", 1)], books[("germany_master", 2)]
    assert v2.declares_needs and not v1.declares_needs
    d1, d2 = v1.model_dump(mode="json"), v2.model_dump(mode="json")
    assert d2.pop("asks") and not d1.pop("asks")
    assert all(t.pop("needs") == [] for t in d1["tasks"])
    for t in d2["tasks"]:
        t.pop("needs")
    # put the removed manual step and the edge that pointed at it back, and the version
    cert = next(t for t in d1["tasks"] if t["template_key"] == "school_certificates")
    d2["tasks"].insert(d1["tasks"].index(cert), copy.deepcopy(cert))
    ua = next(t for t in d2["tasks"] if t["template_key"] == "uni_assist_apply")
    ua["depends_on"].insert(1, {"key": "school_certificates", "hard": True, "pull": True})
    d2["version"] = 1
    assert d2 == d1
    default_registry().validate([v2])


def test_germany_v2_documents_are_needs_of_the_applications():
    v2 = load_playbook_dir(PLAYBOOK_DIR)[("germany_master", 2)]
    assert "school_certificates" not in {t.template_key for t in v2.tasks}
    for key in ("uni_assist_apply", "direct_apply"):
        got = {(n.document, n.evidence) for n in v2.task(key).needs}
        assert got == {("ssc_certificate", "shown"), ("hssc_certificate", "shown")}
    assert v2.asks["ssc_certificate"].shown == "Upload your SSC certificate with subjects and grades"
    assert v2.asks["hssc_certificate"].shown == "Upload your HSSC certificate with subjects and grades"
    assert set(v2.asks) == {"ssc_certificate", "hssc_certificate"}
    for key in ("ssc_certificate", "hssc_certificate"):  # R-17: no new source; the S1 citation is version 1's
        assert [(c.source, str(c.url)) for c in v2.asks[key].citations] == [
            ("S1", "https://www.uni-assist.de/en/tools/info-country-by-country/details-country/country/pk/")]


def test_germany_v2_sidecar_is_a_byte_copy_of_v1():
    side = PLAYBOOK_DIR / "pages"
    assert (side / "germany_master.v2.yaml").read_bytes() == (side / "germany_master.v1.yaml").read_bytes()


def test_fake_v2_playbooks_load_from_needs_dir():
    books = load_playbook_dir(NEEDS_DIR)
    assert set(books) == {("pakistan_inter", 2), ("pakistan_bs", 2), ("ireland_master", 2)}
    assert all(b.declares_needs for b in books.values())
    inter = books[("pakistan_inter", 2)]
    assert inter.asks["education.matric.marks_obtained"].expected.fact == "matric_result_date"
    levels = {(n.fact, n.evidence) for t in inter.tasks for n in t.needs}
    assert ("education.matric.marks_obtained", "stated") in levels and \
        ("education.matric.marks_obtained", "shown") in levels
    ie = books[("ireland_master", 2)]
    assert ie.task("english_proof").fan_out == "programme" and ie.task("english_proof").condition.fact == \
        "english_requirement"
    default_registry().validate(books.values())


def test_fake_v2_files_change_nothing_else_in_the_v1_set():
    assert set(load_playbook_dir(FAKE_DIR)) == {("ireland_master", 1), ("pakistan_bs", 1), ("pakistan_inter", 1)}


# ---- selection -----------------------------------------------------------------------------------

def _all_books():
    return {**load_playbook_dir(FAKE_DIR), **load_playbook_dir(NEEDS_DIR), **load_playbook_dir(PLAYBOOK_DIR)}


def test_select_skips_needs_books_by_default():
    books = _all_books()
    assert select_playbook(books, "PK", "DE", "master").version == 1
    assert select_playbook(books, "PK", "IE", "master").version == 1


def test_select_with_needs_picks_v2():
    books = _all_books()
    assert select_playbook(books, "PK", "DE", "master", with_needs=True).version == 2
    assert select_playbook(books, "PK", "PK", "intermediate", with_needs=True).version == 2


def test_select_with_needs_falls_back_to_plain_when_no_needs_book():
    books = load_playbook_dir(FAKE_DIR)
    assert select_playbook(books, "PK", "IE", "master", with_needs=True).version == 1


def test_select_only_needs_books_without_the_gate_is_an_error():
    books = {k: b for k, b in _all_books().items() if k[1] == 2}
    with pytest.raises(PlaybookError, match="no playbook for PK->DE master"):
        select_playbook(books, "PK", "DE", "master")


def test_newest_plain_ignores_needs_books():
    out = newest_plain(_all_books().values())
    assert {k: b.version for k, b in out.items()} == {
        "germany_master": 1, "ireland_master": 1, "pakistan_bs": 1, "pakistan_inter": 1}


def test_newest_plain_takes_the_highest_plain_version(tmp_path):
    v1, v2 = _ie_needs(), yaml.safe_load(IE.read_text())
    v2["version"] = 3
    v1["version"] = 2
    _write(tmp_path, v1, "a.v2.yaml")
    _write(tmp_path, v2, "a.v3.yaml")
    assert {k: b.version for k, b in newest_plain(load_playbook_dir(tmp_path).values()).items()} == {
        "ireland_master": 3}


def test_routes_bytes_unchanged_with_v2_loaded(engine, clean, os_db):
    from tests.os.test_api_self_serve import P, build_api, me

    api = build_api(engine, os_db, extra_books=load_playbook_dir(NEEDS_DIR))
    got = api.get(f"{P}/routes", headers=me()).content
    assert got == (HERE / "fixtures" / "routes_before_needs.json").read_bytes()


# ---- the compiler's field list -------------------------------------------------------------------

@pytest.mark.req("R-20")
def test_needed_fields_adds_expected_fact():
    books = load_playbook_dir(NEEDS_DIR)
    route, _ = needed_fields(books[("pakistan_inter", 2)])
    assert "matric_result_date" in route
    plain_route, _ = needed_fields(load_playbook_dir(FAKE_DIR)[("pakistan_inter", 1)])
    assert "matric_result_date" not in plain_route


@pytest.mark.req("R-20")
def test_needs_seed_loads(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    assert load_seed(SEED, kb) >= 2
    fact = kb.route_facts("pakistan_inter", ["matric_result_date"], 2027)["matric_result_date"]
    assert fact.value["date"] and fact.url
    assert kb.programme_facts(["ie-p1"], ["english_requirement"], 2027)[("ie-p1", "english_requirement")].value


# ---- review fixes: asks need a source, no unused ask, no repeated need --------------------------------

def test_ask_used_by_a_need_needs_a_citation_when_citations_are_required(tmp_path):
    d = _ie_needs()
    d["require_citations"] = True
    for t in d["tasks"]:
        t["citations"] = [{"source": "S1", "url": "https://source.example/a"}]
    with pytest.raises(PlaybookError, match="asks.*needs a citation"):
        _load(tmp_path, d)
    d["asks"]["education.matric.marks_obtained"]["citations"] = [{"source": "S1", "url": "https://source.example/a"}]
    assert _load(tmp_path, d).asks["education.matric.marks_obtained"].citations[0].source == "S1"


def test_ask_without_a_citation_is_fine_when_citations_are_not_required(tmp_path):
    assert _load(tmp_path, _ie_needs()).declares_needs


def test_ask_that_no_need_uses_is_refused(tmp_path):
    d = _ie_needs()
    d["asks"]["education.matric.marks_total"] = {"stated": "Tell us the total", "which_is_right": "Which total?"}
    with pytest.raises(PlaybookError, match="not needed by any step"):
        _load(tmp_path, d)


def test_same_need_twice_in_one_step_is_refused(tmp_path):
    d = _ie_needs()
    d["tasks"][0]["needs"].append({"fact": "education.matric.marks_obtained", "evidence": "stated"})
    with pytest.raises(PlaybookError, match="more than once"):
        _load(tmp_path, d)


# ---- upgrade never goes back --------------------------------------------------------------------

def test_upgrade_with_the_gate_off_keeps_a_v2_plan_on_v2(engine, clean):
    from sqlalchemy import func, select

    from app.os import models
    from app.os.service import NothingNewer
    from tests.os.test_golden import TEST_STUDENT
    from tests.os.test_replan_events import service

    def revisions(plan_id: int) -> int:
        with engine.connect() as conn:
            return conn.execute(select(func.count()).select_from(models.plan_revisions).where(
                models.plan_revisions.c.plan_id == plan_id)).scalar_one()

    svc = service(engine)
    plan_id = svc.start_plan(TEST_STUDENT, with_needs=True).plan_id
    assert svc._pinned(plan_id).version == 2
    before = revisions(plan_id)
    with pytest.raises(NothingNewer, match="nothing newer"):
        svc.upgrade(plan_id)  # the default gate (off) selects v1, which is older than the pin
    assert svc._pinned(plan_id).version == 2
    assert revisions(plan_id) == before
