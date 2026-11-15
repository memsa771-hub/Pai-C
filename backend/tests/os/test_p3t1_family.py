"""P3-T1 (ADR-001 D1, D5, D14; R-36, R-58): the playbook schema for route families and the family release flag.

Fictional playbooks only: tests/os/family_playbooks (family `alphafam` on the fictional route ZZ -> ZZ). The
byte-for-byte guard compares every shipped and fixture playbook's compiled plans with a snapshot written at the base
commit (tests/os/compile_snapshot.py)."""

import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml
from sqlalchemy import select

from app.os import models, ports
from app.os.compiler import CompileError, SystemsNotResolved, compile_plan, needed_fields
from app.os.contracts.route_contract_v2 import RouteContractV2
from app.os.playbooks import (
    PLAYBOOK_DIR, Playbook, PlaybookError, load_playbook, load_playbook_dir, newest_plain, select_playbook,
)
from app.os.settings import family_flag, load_settings
from tests.os import compile_snapshot

pytestmark = pytest.mark.req("R-36")

HERE = Path(__file__).parent
FAMILY = HERE / "family_playbooks"
FAKE = HERE / "playbooks"
SAMPLES = HERE.parents[1] / "app" / "os" / "contracts" / "samples"
APP_OS = HERE.parents[1] / "app" / "os"
CODE = "alphafam"
FLAG = "CONNECT_FAMILY_ALPHAFAM"
ROUTE = ("ZZ", "ZZ", "intermediate")
FAM = load_playbook(FAMILY / "fam_inter.v1.yaml")
SYSTEMS = load_playbook(FAMILY / "systems" / "fam_systems.v1.yaml")


def data(book: Playbook) -> dict:
    return book.model_dump(mode="json", by_alias=True, exclude_none=True)


def with_tasks(base: dict, *tasks: dict, **top) -> dict:
    return {**base, **top, "tasks": list(tasks)}


PLAIN = {"key": "k", "version": 1, "route": {"origin": "AA", "destination": "BB", "level": "x"},
         "default_timezone": "UTC"}


def step(key: str = "s", **over) -> dict:
    return {"template_key": key, "task_type": "student.act", "title": "Do it", "kind": "student", "inbox_kind": "act",
            **over}


# --- the schema -------------------------------------------------------------------------------------------------------

def test_schema_accepts_the_family_units():
    assert SYSTEMS.family == CODE
    register, apply_place, wait = (SYSTEMS.task(k) for k in ("register", "apply_place", "wait_list"))
    assert register.fan_out == "system" and register.condition.of == "system"
    assert register.anchor.of == "system_calendar" and register.title_placeholders == {"system"}
    assert apply_place.anchor.of == "system" and apply_place.title_placeholders == {"institution", "system", "body"}
    assert SYSTEMS.uses_systems and register.uses_systems and apply_place.uses_systems and not wait.uses_systems
    assert FAM.family == CODE and not FAM.uses_systems


def test_family_alone_is_optional_and_off_for_existing_playbooks():
    for path in compile_snapshot.playbook_files():
        book = load_playbook(path)
        assert book.family is None and not book.uses_systems, path.name


@pytest.mark.parametrize("code", ["Alpha", "alpha-fam", "1alpha", "", "alpha fam"])
def test_family_code_is_a_plain_lowercase_code(code):
    assert Playbook.model_validate(with_tasks(PLAIN, step(), family="alpha_fam1")).family == "alpha_fam1"
    with pytest.raises(ValueError, match="family"):
        Playbook.model_validate(with_tasks(PLAIN, step(), family=code))


@pytest.mark.parametrize("unit", [
    {"fan_out": "system"},
    {"fan_out": "programme", "anchor": {"fact": "d", "of": "system"}},
    {"fan_out": "programme", "anchor": {"fact": "d", "of": "system_calendar"}},
    {"fan_out": "programme", "condition": {"fact": "m", "present": True, "of": "system"}},
    {"fan_out": "programme", "title": "Apply to {institution}"},
])
def test_family_units_need_a_family(unit):
    with pytest.raises(ValueError, match="need the playbook's 'family'"):
        Playbook.model_validate(with_tasks(PLAIN, step(**unit)))
    Playbook.model_validate(with_tasks(PLAIN, step(**unit), family=CODE))  # the same step loads in a family playbook


def test_fan_out_system_without_family_is_refused_by_the_loader(tmp_path):
    raw = data(SYSTEMS)
    raw.pop("family")
    (tmp_path / "bad.v1.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(PlaybookError, match="(?s)bad.v1.yaml.*need the playbook's 'family'"):
        load_playbook_dir(tmp_path)


@pytest.mark.parametrize("unit, says", [
    ({"anchor": {"fact": "d", "of": "system"}}, "anchor.of: system needs a system in scope"),
    ({"anchor": {"fact": "d", "of": "system_calendar"}}, "anchor.of: system_calendar needs a system in scope"),
    ({"condition": {"fact": "m", "in": ["a"], "of": "system"}}, "condition.of: system needs a system in scope"),
    ({"title": "Register with {system}"}, r"not in scope on a step with fan_out: none"),
    ({"fan_out": "system", "title": "Apply to {institution}"}, r"\['institution'\].*fan_out: system"),
    ({"fan_out": "programme", "title": "Apply to {campus}"}, r"unknown title placeholder \{campus\}"),
    ({"fan_out": "programme", "title": "Apply to {system.name}"}, r"unknown title placeholder"),
    ({"fan_out": "programme", "title": "Apply to {0}"}, r"unknown title placeholder"),
    ({"fan_out": "programme", "title": "Apply to {system"}, "is not a valid template"),
    ({"fan_out": "programme", "title": "Apply to {system!r}"}, "conversion or format spec"),
    ({"fan_out": "programme", "title": "Apply to {body:>10}"}, "conversion or format spec"),
    ({"anchor": {"fact": "d", "of": "system", "programme": "visa"}}, "two sources for one date"),
])
def test_misuse_is_refused_at_load(unit, says):
    with pytest.raises(ValueError, match=says):
        Playbook.model_validate(with_tasks(PLAIN, step(**unit), family=CODE))


@pytest.mark.parametrize("unit", [{"fan_out": "region"}, {"anchor": {"fact": "d", "of": "body"}},
                                  {"condition": {"fact": "m", "present": True, "of": "system_calendar"}}])
def test_unknown_values_are_refused(unit):
    known = {"fan_out": "system", "anchor": {"fact": "d", "of": "system_calendar"},
             "condition": {"fact": "m", "present": True, "of": "system"}}
    Playbook.model_validate(with_tasks(PLAIN, step(**known), family=CODE))  # the known values load
    with pytest.raises(ValueError):
        Playbook.model_validate(with_tasks(PLAIN, step(**{"fan_out": "programme", **unit}), family=CODE))


def test_literal_braces_stay_allowed_in_a_title():
    book = Playbook.model_validate(with_tasks(PLAIN, step(title="Send the form {{signed}}")))
    assert book.tasks[0].title == "Send the form {{signed}}" and not book.uses_systems


# --- the compiler -----------------------------------------------------------------------------------------------------

def _contract(refs=("prog-a.test",)) -> RouteContractV2:
    return RouteContractV2.model_validate({
        "contract_version": "2", "source": "self_serve", "external_ref": "fam-1", "student_ref": "fam-student",
        "origin_country": "ZZ", "destination_country": "ZZ", "level": "intermediate",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


def test_compiler_refuses_system_steps_loudly():
    with pytest.raises(SystemsNotResolved, match=r"\['apply_place', 'register'\].*P3-T4") as e:
        compile_plan(_contract(), SYSTEMS, {}, {}, date(2027, 2, 1))
    assert isinstance(e.value, NotImplementedError) and isinstance(e.value, CompileError)


@pytest.mark.parametrize("unit", [{"fan_out": "system"}, {"fan_out": "programme", "title": "Apply to {body}"},
                                  {"fan_out": "programme", "anchor": {"fact": "d", "of": "system"}},
                                  {"fan_out": "programme", "condition": {"fact": "m", "present": True, "of": "system"}}])
def test_each_system_unit_alone_is_refused_never_dropped(unit):
    book = Playbook.model_validate(with_tasks(PLAIN, step("plain"), step("sys", **unit), family=CODE))
    with pytest.raises(SystemsNotResolved, match=r"\['sys'\]"):
        compile_plan(_contract(), book, {}, {}, date(2027, 2, 1))


def test_a_family_playbook_without_system_units_compiles():
    draft = compile_plan(_contract(), FAM, {}, {}, date(2027, 2, 1))
    assert {t.instance_key for t in draft.tasks} >= {"apply_form", "offer@prog-a.test"}


def test_system_facts_are_never_read_as_route_or_programme_facts():
    assert needed_fields(SYSTEMS) == (set(), set())


# --- byte-for-byte (guards: these pass on the base too) ---------------------------------------------------------------

def test_every_existing_playbook_compiles_byte_for_byte_as_at_the_base():
    """Germany and every fixture playbook, compiled with no facts, with date facts and with an empty student, give
    the same bytes as the snapshot written at base 30d70d2b."""
    assert compile_snapshot.render() == compile_snapshot.SNAPSHOT.read_text(encoding="utf-8")


def test_selection_and_listing_unchanged_without_family_playbooks():
    books = load_playbook_dir(FAKE) | load_playbook_dir()
    routes = {(b.route.origin, b.route.destination, b.route.level) for b in books.values()}
    for route in routes:
        assert select_playbook(books, *route) is select_playbook(books, *route, released=None)
        assert select_playbook(books, *route) is select_playbook(books, *route, released={CODE})
    assert newest_plain(books.values()) == newest_plain(books.values(), released=())


# --- the release flag: pure ---------------------------------------------------------------------------------------------

def test_flag_name_is_derived_from_the_family_code():
    assert family_flag(CODE) == FLAG
    assert family_flag("some_family") == "CONNECT_FAMILY_SOME_FAMILY"


@pytest.mark.parametrize("value, on", [(None, False), ("", False), ("false", False), ("0", False), ("on", True),
                                       ("true", True), ("1", True), ("yes", True)])
def test_flag_is_read_through_os_settings_and_off_by_default(value, on):
    env = {"DATABASE_URL": "x"} | ({} if value is None else {FLAG: value})
    settings = load_settings(env)
    assert (CODE in settings.released_families) is on
    assert settings.released_families <= {CODE}


def test_select_playbook_offers_a_family_only_while_released():
    books = {(FAM.key, FAM.version): FAM}
    with pytest.raises(PlaybookError):
        select_playbook(books, *ROUTE)
    with pytest.raises(PlaybookError):
        select_playbook(books, *ROUTE, released={"otherfam"})
    assert select_playbook(books, *ROUTE, released={CODE}) is FAM
    assert select_playbook(books, *ROUTE, released=None) is FAM  # a reader of a plan that exists


def test_newest_plain_lists_a_family_only_while_released():
    assert newest_plain([FAM], released=()) == {}
    assert newest_plain([FAM], released={CODE}) == {FAM.key: FAM}
    assert newest_plain([FAM]) == {FAM.key: FAM}  # readers of existing plans (packs, programme facts) still see it


# --- the release flag: routes, supports, selection and pinned plans ------------------------------------------------------

def _services(engine, os_db, on: bool):
    from app.os.api.services import make_services

    env = {"OS_DATABASE_URL": os_db} | ({FLAG: "on"} if on else {})
    books = load_playbook_dir(FAKE) | load_playbook_dir() | load_playbook_dir(FAMILY) | load_playbook_dir(FAMILY / "v2")
    return make_services(load_settings(env), engine=engine, playbooks=books, today=lambda: date(2027, 1, 20))


@pytest.fixture
def both(engine, clean, os_db):
    from app.os.knowledge.programmes import Programme, ProgrammeStore

    ProgrammeStore(engine, "pai").upsert(Programme(
        ref="fam-p1.test", route_key=FAM.key, university="University", name="Programme fam-p1", aliases=(),
        start_urls=("https://fam.test/p1",), official_domains=("fam.test",)))
    yield _services(engine, os_db, on=False), _services(engine, os_db, on=True)
    ports.configure(None)


@pytest.fixture
def without_family(engine, clean, os_db):
    from app.os.api.services import make_services

    return make_services(load_settings({"OS_DATABASE_URL": os_db}), engine=engine,
                         playbooks=load_playbook_dir(FAKE) | load_playbook_dir(), today=lambda: date(2027, 1, 20))


def _routes(svc):
    from app.os.api import self_serve
    from app.os.ports import plan_query

    ports.configure(svc)
    return plan_query.routes(), self_serve.routes_out(svc.plans)


def test_flag_off_routes_are_byte_for_byte_as_without_the_family(both, without_family):
    off, _ = both
    assert json.dumps(_routes(off)) == json.dumps(_routes(without_family))


def test_flag_off_the_family_is_not_listed_on_it_is(both):
    off, on = both
    counsellor, student = _routes(off)
    assert FAM.key not in {r["key"] for r in counsellor} | {r["key"] for r in student}
    counsellor, student = _routes(on)
    fam = next(r for r in counsellor if r["key"] == FAM.key)
    assert (fam["origin"], fam["destination"], fam["level"], fam["intake_terms"]) == (*ROUTE, ["winter"])
    assert next(r for r in student if r["key"] == FAM.key)["version"] == 2  # the newest version, as for any route


def test_flag_off_the_route_is_not_supported_on_it_is(both):
    from app import pai_os_bridge
    from app.os.ports import plan_source

    off, on = both
    ports.configure(off)
    assert plan_source.supports(*ROUTE) is False and pai_os_bridge.route_supported(*ROUTE) is False
    assert plan_source.supports("PK", "DE", "master") is True  # other routes as before
    ports.configure(on)
    assert plan_source.supports(*ROUTE) is True and pai_os_bridge.route_supported(*ROUTE) is True


def test_flag_off_no_new_plan_on_it_one_is_made(both):
    off, on = both
    with pytest.raises(PlaybookError):
        off.plans.start_plan(_contract(("fam-p1.test",)))
    ref = on.plans.start_plan(_contract(("fam-p1.test",)))
    assert _pin(on, ref.plan_id) == (FAM.key, 2)


def _pin(svc, plan_id):
    pins = models.playbook_pins
    with svc.engine.connect() as conn:
        row = conn.execute(select(pins.c.playbook_key, pins.c.version).where(pins.c.plan_id == plan_id)).one()
    return tuple(row)


def test_a_pinned_plan_keeps_compiling_revising_and_upgrading_with_the_flag_off(both):
    off, on = both
    on.plans.playbooks = {k: v for k, v in on.plans.playbooks.items() if k != (FAM.key, 2)}  # pin v1 while it is on
    ref = on.plans.start_plan(_contract(("fam-p1.test",)))
    assert _pin(on, ref.plan_id) == (FAM.key, 1)
    # the flag goes off: the running plan is still served
    again = off.plans.start_plan(_contract(("fam-p1.test",)))
    assert again.plan_id == ref.plan_id
    off.plans.recompile(ref.plan_id, "test:flag_off")  # compiles with its pinned playbook; no error
    off.plans.change_programmes(ref.plan_id, lambda c: list(c.programmes), "test:flag_off")
    assert off.plans.check_newer(ref.plan_id) is True  # v2 of its own family is still its upgrade line
    off.plans.upgrade(ref.plan_id)
    assert _pin(off, ref.plan_id) == (FAM.key, 2)


def _decision(n: int) -> dict:
    sample = json.loads((SAMPLES / "v2" / "decision_chosen_de.json").read_text())
    return {**sample, "decision_id": f"fam-d{n}", "decision_version": n,
            "chosen_at": f"2027-01-{10 + n:02d}T09:00:00+05:00", "origin_country": "ZZ", "destination_country": "ZZ",
            "level": "intermediate", "programmes": [{"programme_ref": "fam-p1.test", "rank": 1}]}


def _intake(svc, export):
    from app.os.adapters.counsellor.intake import process
    from app.os.adapters.counsellor.store import IntakeStore

    store = IntakeStore(svc.engine, "pai")
    store.add(export, "0" * 64)
    return process(svc, store.get(export["decision_id"]))


def test_counsellor_decision_flag_off_is_refused_on_is_planned(both):
    off, on = both
    r = _intake(off, _decision(1))
    assert (r.status, r.reason) == ("refused", "route_not_supported")
    r = _intake(on, _decision(2))
    assert (r.status, r.reason) == ("planned", None)


def test_counsellor_plan_pinned_to_a_family_still_revises_with_the_flag_off(both):
    off, on = both
    first = _intake(on, _decision(1))
    assert first.status == "planned"
    r = _intake(off, _decision(2))
    assert (r.status, r.plan_id) == ("revised", first.plan_id)


@pytest.fixture
def fam_api(engine, clean, os_db):
    """The self-serve API with the family loaded and its flag off (fix round 1: programme requests)."""
    from tests.os.test_api_self_serve import build_api

    books = load_playbook_dir(FAMILY) | load_playbook_dir(FAMILY / "v2")
    yield build_api(engine, os_db, extra_books=books)
    ports.configure(None)


def _ask(api, student):
    from tests.os.test_api_self_serve import P, me

    return api.post(f"{P}/programmes/requests", headers=me(student), json={
        "route": FAM.key, "intake_year": 2027, "university": "Uni F", "name": "Course F",
        "url": "https://uni-f.test/course"})


def _requests(engine) -> int:
    with engine.connect() as conn:
        return len(conn.execute(select(models.programme_requests.c.id)).all())


def test_programme_request_on_an_unreleased_family_is_refused_and_never_researched(fam_api):
    r = _ask(fam_api, "fam-student")
    assert r.status_code == 422 and r.json()["detail"] == "unknown route 'fam_inter'"
    assert fam_api.fake.calls == [] and _requests(fam_api.engine) == 0


def test_programme_request_allowed_for_a_student_pinned_to_the_family(fam_api, engine, os_db):
    on = _services(engine, os_db, on=True)
    on.plans.start_plan(_contract(("fam-p1.test",)))  # the student's plan, pinned while the flag was on
    r = _ask(fam_api, "fam-student")
    assert r.status_code == 202 and r.json()["created"] and len(fam_api.fake.calls) == 1
    assert _ask(fam_api, "someone-else").status_code == 422  # only the student with the plan


def test_released_for_a_plan_without_a_pin_counts_only_the_flags(both):
    off, on = both
    assert off.plans._released_for(987654) == frozenset()
    assert on.plans._released_for(987654) == {CODE}


def test_self_serve_start_waits_for_the_flag(both):
    """The self-serve builder offers the same: no new plan on an unreleased family route."""
    from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice
    from app.os.routes import builder

    off, _ = both
    with pytest.raises(builder.NotAllowed, match="unknown route 'fam_inter'"):
        builder.start(off.plans, "fam-student", FAM.key, IntakeRef(term="winter", year=2027),
                      [ProgrammeChoice(programme_ref="fam-p1.test", rank=1)])


# --- R-58: no family name in code -----------------------------------------------------------------------------------------

def family_codes() -> set[str]:
    """The family codes in data: the allow-lists' `family` fields, and this file's fictional one."""
    codes = {CODE}
    for path in (APP_OS / "knowledge" / "sources" / "lists").glob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if raw.get("family"):
            codes.add(str(raw["family"]))
    return codes


def family_names_in_code(root: Path, codes: set[str]) -> list[str]:
    """A family named in code: its release flag spelled out, or a family compared with a quoted code."""
    flag = re.compile(r"CONNECT_FAMILY_[A-Za-z0-9]")
    alt = "|".join(map(re.escape, sorted(codes)))
    quoted = re.compile(rf"""\bfamily\b.*["']({alt})["']|["']({alt})["'].*\bfamily\b""")
    found = []
    for path in root.rglob("*.py"):
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if flag.search(line) or quoted.search(line):
                found.append(f"{path.relative_to(root).as_posix()}:{n}")
    return sorted(found)


@pytest.mark.req("R-58")
def test_no_family_name_in_os_code():
    assert len(family_codes()) >= 3  # the data's families are found, so the check checks something
    assert family_names_in_code(APP_OS, family_codes()) == []


@pytest.mark.req("R-58")
def test_family_name_check_catches_a_violation(tmp_path):
    (tmp_path / "a.py").write_text('FLAG = "CONNECT_FAMILY_ALPHAFAM"\n')
    (tmp_path / "b.py").write_text('if book.family == "alphafam":\n    pass\n')
    (tmp_path / "c.py").write_text('PREFIX = "CONNECT_FAMILY_"\nlevel = "alphafam"\n')
    assert family_names_in_code(tmp_path, {CODE}) == ["a.py:1", "b.py:1"]
