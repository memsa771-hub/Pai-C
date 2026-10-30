"""Slice 4 Task 8: the self-serve builder, swap and remove, through PlanService and the kernel (S4-D9, S4-D10, Q3)."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.os import clock, models
from app.os.api import make_services
from app.os.contracts.route_contract import IntakeRef, ProgrammeChoice, RouteContract
from app.os.kernel import StaleDraft
from app.os.knowledge import Fact, SqlKnowledge
from app.os.knowledge.programmes import Programme, ProgrammeStore
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir
from app.os.routes.builder import NotAllowed, SwapLimit, remove, start, swap
from app.os.settings import load_settings

FAKE = Path(__file__).parent / "playbooks"
NOW = datetime(2027, 3, 1, 9, tzinfo=timezone.utc)
WINTER = IntakeRef(term="winter", year=2027)


@pytest.fixture
def svc(engine, clean, os_db):
    settings = load_settings({"OS_DATABASE_URL": os_db, "OS_ENABLED": "true"})
    books = load_playbook_dir(FAKE) | load_playbook_dir(PLAYBOOK_DIR)
    s = make_services(settings, engine=engine, playbooks=books, today=lambda: date(2027, 3, 1))
    store, kb = ProgrammeStore(engine, "pai"), SqlKnowledge(engine, "pai")
    for ref, route in (("p1", "ireland_master"), ("p2", "ireland_master"), ("p3", "ireland_master"),
                       ("p4", "ireland_master"), ("g1", "germany_master"), ("bare", "ireland_master")):
        store.upsert(Programme(ref=ref, route_key=route, university="Uni X", name=f"Programme {ref}", aliases=(),
                               start_urls=(f"https://uni.example/{ref}",), official_domains=("uni.example",)))
        if ref != "bare":  # "bare" has no facts yet
            kb.upsert("programme", ref, "deadline_close", Fact({"date": "2027-07-15"}, "Apply by 15 July",
                                                                "https://uni.example/d", NOW, 2027, "confirmed"))
    return s


def choices(*refs) -> list[ProgrammeChoice]:
    return [ProgrammeChoice(programme_ref=r, rank=i + 1) for i, r in enumerate(refs)]


def programmes(svc, plan_id) -> list[str]:
    with svc.engine.connect() as conn:
        c = conn.execute(select(models.plans.c.contract).where(models.plans.c.id == plan_id)).scalar_one()
    return [p["programme_ref"] for p in sorted(c["programmes"], key=lambda p: p["rank"])]


def tasks(svc, plan_id) -> dict[str, str]:
    T = models.tasks
    with svc.engine.connect() as conn:
        return {r.instance_key: r.state for r in conn.execute(select(T.c.instance_key, T.c.state)
                                                              .where(T.c.plan_id == plan_id))}


def test_start_builds_self_serve_contract(svc):
    ref = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2"))
    assert ref.created
    with svc.engine.connect() as conn:
        row = conn.execute(select(models.plans).where(models.plans.c.id == ref.plan_id)).one()
    c = RouteContract.model_validate(row.contract)
    assert (c.source, c.external_ref, c.student_ref) == ("self_serve", "self:stu-1:ireland_master:winter:2027", "stu-1")
    assert (c.origin_country, c.destination_country, c.level) == ("PK", "IE", "master")
    assert programmes(svc, ref.plan_id) == ["p1", "p2"] and "apply@p1" in tasks(svc, ref.plan_id)


def test_start_twice_returns_existing(svc):
    a = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1"))
    b = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1"))
    assert (b.plan_id, b.created) == (a.plan_id, False)


def test_start_completes_choose_task(svc):
    ref = start(svc.plans, "stu-1", "germany_master", WINTER, choices("g1"))
    assert tasks(svc, ref.plan_id)["choose_programmes"] == "done"
    T = models.tasks
    with svc.engine.connect() as conn:
        result = conn.execute(select(T.c.result).where(T.c.plan_id == ref.plan_id,
                                                       T.c.instance_key == "choose_programmes")).scalar_one()
    assert result == {"programmes": ["g1"]}


def test_start_without_choose_task_route(svc):
    ref = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1"))
    assert not any(k.startswith("choose") for k in tasks(svc, ref.plan_id))


def test_other_route_programme_refused(svc):
    with pytest.raises(NotAllowed, match="g1"):
        start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "g1"))
    with pytest.raises(NotAllowed, match="nope"):
        start(svc.plans, "stu-1", "ireland_master", WINTER, choices("nope"))


def test_unknown_route_refused(svc):
    with pytest.raises(NotAllowed, match="route"):
        start(svc.plans, "stu-1", "mars_master", WINTER, choices("p1"))


def test_eleven_programmes_refused(svc):
    with pytest.raises(NotAllowed, match="10"):
        start(svc.plans, "stu-1", "ireland_master", WINTER, choices(*[f"x{i}" for i in range(11)]))


def test_swap_revises_plan(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2")).plan_id
    assert swap(svc.plans, "stu-1", plan, "p1", "p3") is not None
    t = tasks(svc, plan)
    assert "apply@p3" in t and not any(k == "apply@p1" for k in t)  # p1's unstarted task was cancelled, renamed
    assert any(k.startswith("apply@p1") and s == "cancelled" for k, s in t.items())


def test_swap_keeps_rank(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2")).plan_id
    swap(svc.plans, "stu-1", plan, "p1", "p3")
    assert programmes(svc, plan) == ["p3", "p2"]


def test_swap_needs_facts_and_same_route(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1")).plan_id
    with pytest.raises(NotAllowed, match="research"):
        swap(svc.plans, "stu-1", plan, "p1", "bare")
    with pytest.raises(NotAllowed, match="g1"):
        swap(svc.plans, "stu-1", plan, "p1", "g1")
    with pytest.raises(NotAllowed, match="p2"):
        swap(svc.plans, "stu-1", plan, "p2", "p3")  # p2 is not in the plan


def test_swap_refused_when_started(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2")).plan_id
    T = models.tasks
    with svc.engine.begin() as conn:  # a test shortcut: the student already applied to p1
        conn.execute(T.update().where(T.c.plan_id == plan, T.c.instance_key == "apply@p1").values(state="done"))
    with pytest.raises(NotAllowed, match="started"):
        swap(svc.plans, "stu-1", plan, "p1", "p3")


def test_fourth_swap_in_a_day_refused(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2")).plan_id
    for out, new in (("p1", "p3"), ("p3", "p4"), ("p4", "p1")):
        swap(svc.plans, "stu-1", plan, out, new)
    with pytest.raises(SwapLimit):
        swap(svc.plans, "stu-1", plan, "p1", "p3")
    with pytest.raises(SwapLimit):
        remove(svc.plans, "stu-1", plan, "p2")  # removals count too


def test_swap_stale_contract_retries(svc, monkeypatch):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2")).plan_id
    real, calls = svc.kernel.change_contract, {"n": 0}

    def racing(*args, **kwargs):  # another change lands between compile and write, once
        calls["n"] += 1
        if calls["n"] == 1:
            raise StaleDraft("changed meanwhile")
        return real(*args, **kwargs)

    monkeypatch.setattr(svc.kernel, "change_contract", racing)
    swap(svc.plans, "stu-1", plan, "p1", "p3")
    assert calls["n"] == 2 and programmes(svc, plan) == ["p3", "p2"]


def test_change_contract_refuses_stale_based_on(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1")).plan_id
    contract, _ = svc.plans._contract(plan)
    draft = svc.plans.compile(contract, svc.plans._pinned(plan))
    with pytest.raises(StaleDraft):
        svc.kernel.change_contract(plan, contract, draft, "test", based_on="not-the-current-sha")


def test_remove(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2", "p3")).plan_id
    remove(svc.plans, "stu-1", plan, "p2")
    assert programmes(svc, plan) == ["p1", "p3"]


def test_remove_last_programme_refused(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1")).plan_id
    with pytest.raises(NotAllowed, match="last"):
        remove(svc.plans, "stu-1", plan, "p1")


def test_only_own_plan(svc):
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2")).plan_id
    with pytest.raises(NotAllowed, match="plan"):
        swap(svc.plans, "stu-2", plan, "p1", "p3")
    with pytest.raises(NotAllowed, match="plan"):
        remove(svc.plans, "stu-2", plan, "p1")


def test_start_and_swap_record_starting_verdicts(svc):
    """Without this, a student's first confirmed document would only be recorded, never noted (S4-D7)."""
    S = models.eligibility_seen
    plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1")).plan_id
    with svc.engine.connect() as conn:
        assert conn.execute(select(S.c.programme_ref, S.c.verdict)).all() == [("p1", "unknown")]  # only a deadline fact here: requirements not researched
    swap(svc.plans, "stu-1", plan, "p1", "p2")
    with svc.engine.connect() as conn:
        assert {r.programme_ref for r in conn.execute(select(S.c.programme_ref))} == {"p1", "p2"}


def test_swap_window_follows_the_shared_clock(svc):
    """Slice 9a: the 24 hour programme-change window runs on the shared clock, so advancing a rehearsal day clears it."""
    shift = [timedelta(days=60)]
    clock.configure(lambda: shift[0])
    try:
        plan = start(svc.plans, "stu-1", "ireland_master", WINTER, choices("p1", "p2")).plan_id
        for out, new in (("p1", "p3"), ("p3", "p4"), ("p4", "p1")):
            swap(svc.plans, "stu-1", plan, out, new)
        with pytest.raises(SwapLimit):
            swap(svc.plans, "stu-1", plan, "p1", "p3")
        shift[0] += timedelta(hours=25)
        swap(svc.plans, "stu-1", plan, "p1", "p3")
    finally:
        clock.configure(None)
