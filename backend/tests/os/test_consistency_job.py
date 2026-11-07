"""P1-T10 A3 (R-05): the consistency job over a real PAI OS on Postgres and the Counsellor on SQLite. Worlds from T5
(Germany, a student who chose and was planned). One planted mismatch per rule gives exactly one open case; a repeat
touches it; the job repairs nothing and says nothing to the student. Fictional students."""

import dataclasses
import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import func, insert, select, update

from app import pai_os_bridge as bridge
from app.config import config
from app.models import RouteDecision, VaultVersion
from app.os import models, ports
from app.os.ports import consistency as port
from tests.os.connect_check import assert_consistent, findings
from tests.os.test_connect_t5_flow import (  # noqa: F401 - fixtures
    chosen,
    germany_student,
    level,
    no_chat,
    row_counts,
    run_os,
    svc,
    world,
)
from tests.test_roadmap_choice_api import choose_with, post, vault
from tests.os.test_connect_t5_flow import WINTER
from tests.test_roadmap_api import data

pytestmark = pytest.mark.req("R-05")
LATER = lambda: datetime.now(timezone.utc) + timedelta(hours=1)  # noqa: E731 - nothing is "in flight" an hour on
OS_ROWS = (models.outbox, models.events, models.support_cases)


def os_counts(engine) -> list[int]:
    with engine.connect() as conn:
        return [conn.execute(select(func.count()).select_from(t)).scalar() for t in OS_ROWS]


def planned(client, who, params):
    vault((client, who, params))
    body = data(choose_with(client, params, destination="DE", places=[{"ref": "ovgu-eeit", "rank": 1}], intake=WINTER))
    assert body["choice"]["os_supported"] is True


def job(who, **kw):
    with who.factory() as db:
        return bridge.consistency_run(db, mode="nightly", now=LATER(), **kw)


def open_cases():
    return [(c.rule, tuple(c.codes)) for c in port.cases("open")]


def test_a_clean_world_has_no_finding(world):
    with germany_student() as (client, who, params), level("master"):
        planned(client, who, params)
        assert run_os(world) == [("planned", None)]
        got = job(who)
        assert got["findings"] == {} and got["errors"] == 0 and got["students"] == 1
        assert open_cases() == []
        assert assert_consistent(who.factory)["findings"] == {}


def plant_rule1(world, who, client, params):  # the decision was delivered, nobody ran the OS intake
    return None


def plant_rule2(world, who, client, params):
    run_os(world)
    with world.engine.begin() as conn:
        conn.execute(update(models.plans).where(models.plans.c.source == "counsellor").values(contract_sha256="f" * 64))


def plant_rule3(world, who, client, params):
    run_os(world)
    data(post(client, params, "withdraw"))  # delivered, but the OS intake has not stopped the plan


def plant_rule4(world, who, client, params):
    run_os(world)
    with who.factory() as db:
        row = db.scalar(select(RouteDecision).where(RouteDecision.workspace_id == who.workspace_id))
        row.steps_done = ["a-step"]
        db.commit()


def plant_rule5(world, who, client, params):
    run_os(world)
    with who.factory() as db:
        db.add(VaultVersion(workspace_id=who.workspace_id, version=7, key_versions={}))
        db.commit()


def plant_rule6(world, who, client, params):
    run_os(world)
    with world.engine.begin() as conn:
        conn.execute(insert(models.documents).values(
            tenant_id="pai", student_ref=who.workspace_id, doc_type="transcript", type_version=1, filename="a.pdf",
            content_type="application/pdf", size=1, sha256="1" * 64, status="confirmed", file_ref="no-such-file"))


PLANTS = [(1, plant_rule1, ("no_plan",)), (2, plant_rule2, ("contract_hash",)),
          (3, plant_rule3, ("plan_not_stopped",)), (4, plant_rule4, ("checklist_ticked",)),
          (5, plant_rule5, ("vault_behind",)), (6, plant_rule6, ("file_missing",))]


@contextmanager
def parts_on():
    """Every part a rule needs (the T5 world switches on the hand-off and the roadmap only)."""
    with patch.object(config, "CONNECT_STUDENT_FACTS", True, create=True), \
            patch.object(config, "CONNECT_ONE_UPLOAD", True, create=True):
        yield


@pytest.mark.parametrize("rule,plant,codes", PLANTS, ids=[f"rule{r}" for r, _, _ in PLANTS])
def test_a_planted_mismatch_opens_one_case_and_a_repeat_touches_it(world, rule, plant, codes):
    with germany_student() as (client, who, params), level("master"), parts_on():
        planned(client, who, params)
        plant(world, who, client, params)
        before, rows = row_counts(who), os_counts(world.engine)
        first = job(who)
        assert first["findings"] == {rule: 1} and (first["opened"], first["touched"]) == (1, 0)
        assert open_cases() == [(rule, codes)]
        again = job(who)
        assert (again["opened"], again["touched"]) == (0, 1) and len(open_cases()) == 1
        no_chat(who, before)  # nothing was said to the student
        assert os_counts(world.engine) == rows  # no outbox, event or support-case row of the OS


def planted_view(rule, replace):
    """Rules 7 and 8 cannot be planted in the database (a unique index; a hand-made exclusion): the pure inputs are."""
    real = bridge.os_consistency.side if rule == 7 else bridge.consistency_rules.counsellor_side

    def wrapped(*args, **kw):
        return dataclasses.replace(real(*args, **kw), **replace)

    return patch.object(bridge.os_consistency, "side", wrapped) if rule == 7 else \
        patch.object(bridge.consistency_rules, "counsellor_side", wrapped)


@pytest.mark.parametrize("rule,replace,codes", [
    (7, {"duplicate_requests": (("fact", "education.matric.marks_obtained", 2),)}, ("duplicate_request",)),
    (8, {"excluded_fields": ("computer_science",), "stage_h_fields": ("computer_science",)}, ("in_stage_h",))])
def test_rules_7_and_8_open_a_case(world, rule, replace, codes):
    with germany_student() as (client, who, params), level("master"), parts_on():
        planned(client, who, params)
        run_os(world)
        with planted_view(rule, replace):
            got = job(who)
            assert got["findings"] == {rule: 1} and open_cases() == [(rule, codes)]
            assert job(who)["touched"] == 1


def test_a_resolved_case_with_the_mismatch_still_there_opens_a_new_case(world):
    with germany_student() as (client, who, params), level("master"):
        planned(client, who, params)
        plant_rule2(world, who, client, params)
        job(who)
        (case,) = port.cases("open")
        assert port.resolve(case.id, "looked at it")
        assert open_cases() == []
        again = job(who)
        assert again["opened"] == 1 and len(port.cases("open")) == 1 and len(port.cases()) == 2


def test_the_job_repairs_nothing(world):
    with germany_student() as (client, who, params), level("master"):
        planned(client, who, params)
        plant_rule2(world, who, client, params)
        with world.engine.connect() as conn:
            before = conn.execute(select(models.plans)).all()
        job(who)
        with world.engine.connect() as conn:
            assert conn.execute(select(models.plans)).all() == before


def test_off_reads_nothing_and_writes_nothing(world):
    with germany_student() as (client, who, params), level("master"):
        planned(client, who, params)
        run_os(world)
        boom = patch.object(bridge.os_consistency, "side", side_effect=AssertionError("must not be read"))
        with boom, patch.object(config, "CONNECT_HANDOFF", False):
            assert job(who) == {"skipped": "off"}
        with world.engine.begin() as conn:
            conn.execute(update(models.modules).values(enabled=False))
        with boom:
            assert job(who) == {"skipped": "off"}
        assert port.cases() == []
        with world.engine.connect() as conn:
            assert conn.execute(select(func.count()).select_from(models.consistency_runs)).scalar() == 0


def test_not_mounted_is_reported(world):
    ports.configure(None)
    with germany_student() as (client, who, params), who.factory() as db:
        assert bridge.consistency_run(db) == {"mounted": False}


def test_one_students_error_does_not_stop_the_others_and_the_log_names_no_student(world, caplog):
    with germany_student() as (client, who, params), level("master"):
        planned(client, who, params)
        plant_rule2(world, who, client, params)
        real = bridge.os_consistency.side

        def side(student, export):
            if student == who.workspace_id:
                raise RuntimeError(f"secret {student}")
            return real(student, export)

        with caplog.at_level(logging.INFO), patch.object(bridge.os_consistency, "side", side):
            got = job(who)
        assert got["errors"] == 1
        assert who.workspace_id not in caplog.text and "secret" not in caplog.text and "RuntimeError" in caplog.text
        caplog.clear()
        with caplog.at_level(logging.INFO):
            job(who)
        assert caplog.records and who.workspace_id not in caplog.text  # the finding line holds rule numbers and counts


def test_the_end_of_test_check_reports_the_rule_and_codes_without_values(world):
    with germany_student() as (client, who, params), level("master"):
        planned(client, who, params)
        plant_rule2(world, who, client, params)
        with pytest.raises(AssertionError) as caught:
            assert_consistent(who.factory)
        assert "{2: 1}" in str(caught.value) and who.workspace_id not in str(caught.value)
        assert port.cases() == []  # the end-of-test check writes no case


def test_the_end_of_test_check_does_one_sweep_and_the_intake(world):
    with germany_student() as (client, who, params), level("master"):
        planned(client, who, params)  # delivered, not yet planned: settled finds it...
        assert findings(who.factory, sweep=False)["findings"] == {1: 1}
        assert assert_consistent(who.factory)["findings"] == {}  # ...and one sweep with the intake settles it


def test_the_cli_runs_and_prints_counts_only(world, capsys):
    from scripts import connect_consistency as cli

    with germany_student() as (client, who, params), level("master"):
        planned(client, who, params)
        plant_rule2(world, who, client, params)
        with who.factory() as db:
            with patch.object(bridge, "datetime", wraps=datetime) as clock:
                clock.now.return_value = LATER()
                assert cli.main(["run"], db=db) == 1
        out = capsys.readouterr().out
        assert "rule 2: 1" in out and "opened: 1" in out and who.workspace_id not in out
        with who.factory() as db:
            assert cli.main(["status"], db=db) == 0
        out = capsys.readouterr().out
        assert "rule 2: 1" in out and "open cases: 1" in out and who.workspace_id not in out
