"""P1-T3 Task 7 (R-10, R-79): the whole choice-and-consent journey against a real PAI OS. The Counsellor side is the
real HTTP API and the real guardian link routes on a student session; the OS side is the real services behind the
ports on Postgres, with the fake Pakistan bachelor route. Each step delivers (as the request does), runs the OS
intake and asserts the OS plan state. Fictional students, an invented parent address, a stubbed mailer."""

from contextlib import contextmanager
from unittest.mock import patch

import pytest
from sqlalchemy import func, insert, select

from app import pai_os_bridge as bridge
from app.config import config
from app.memory.vault import VaultService
from app.models import GuardianConsent, OsOutbox
from app.os import models, ports
from app.os.adapters.counsellor.intake import process
from app.os.adapters.counsellor.store import IntakeStore
from app.security import rate_limit
from app.services import auth_emails
from tests.os.test_counsellor_intake_v2 import svc  # noqa: F401 - the fixture is used by name
from tests.test_roadmap_api import TOKEN, data, pre_eng
from tests.test_roadmap_choice_api import EMAIL, FIELD, choose_with, post, rows, vault
from tests.os.connect_check import assert_consistent

pytestmark = [pytest.mark.req("R-10"), pytest.mark.req("R-79")]

PLAN = models.plans
WINTER = {"term": "winter", "year": 2027}
PK_PLACE = [{"ref": "pk-p1", "rank": 1}]


@pytest.fixture
def world(svc, engine, monkeypatch):  # noqa: F811
    """PAI OS on its ports with the Counsellor module on, the flag on, the mailer stubbed. Yields the sent mails."""
    with engine.begin() as conn:
        conn.execute(insert(models.modules).values(module="counsellor", tenant_id="pai", enabled=True))
    ports.configure(svc)
    rate_limit.reset()
    mails = []
    monkeypatch.setattr(auth_emails, "send_email",
                        lambda to, subject, html, text_body=None: mails.append({"to": to, "text": text_body}) or True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    with patch.object(config, "CONNECT_HANDOFF", True, create=True):
        try:
            yield mails
        finally:
            ports.configure(None)
            rate_limit.reset()


@contextmanager
def student(dob="2000-01-01"):
    with pre_eng() as (client, who, params):
        vault((client, who, params), dob=dob)
        yield client, who, params


def run_os(svc) -> list[tuple[str, str | None]]:  # noqa: F811
    """What the OS worker does with the intake rows still pending, oldest first: (status, reason) of each."""
    store = IntakeStore(svc.engine, "pai")
    done = []
    for intake in store.pending():
        result = process(svc, intake)
        store.finish(intake.id, result.status, result.reason, result.plan_id)
        done.append((result.status, result.reason))
    return done


def plans_of(svc, who) -> list:  # noqa: F811
    with svc.engine.connect() as conn:
        return list(conn.execute(select(PLAN.c.id, PLAN.c.status, PLAN.c.external_ref, PLAN.c.contract)
                                 .where(PLAN.c.student_ref == who.workspace_id)))


def events_of(svc, plan_id: int) -> list[str]:  # noqa: F811
    E = models.events
    with svc.engine.connect() as conn:
        return list(conn.execute(select(E.c.type).where(E.c.plan_id == plan_id,
                                                        E.c.type.in_(("plan_paused", "plan_resumed")))
                                 .order_by(E.c.id)).scalars())


def count(svc, table) -> int:  # noqa: F811
    with svc.engine.connect() as conn:
        return conn.execute(select(func.count()).select_from(table)).scalar()


def outbox(who) -> list:
    with who.factory() as db:
        return [(o.status, o.last_error) for o in db.scalars(
            select(OsOutbox).where(OsOutbox.workspace_id == who.workspace_id).order_by(OsOutbox.key))]


def link_token(mail) -> str:
    return next(part for part in mail["text"].split() if "/guardian/" in part).rsplit("/", 1)[1]


def public(client, method, path, status=200):
    response = getattr(client, method)(f"/v1/guardian/{path}")
    assert response.status_code == status, response.text
    return response.json()["data"]


@pytest.mark.connect_row("6.4")
def test_an_adult_chooses_withdraws_and_gives_consent_again(svc, world):  # noqa: F811
    with student() as (client, who, params):
        # 1. a supported route with a place and an intake: the plan is made
        body = data(choose_with(client, params, destination="PK", places=PK_PLACE, intake=WINTER))
        assert body["choice"]["os_supported"] is True and body["choice"]["consent"]["student"] == "given"
        assert outbox(who) == [("delivered", None)]
        assert run_os(svc) == [("planned", None)]
        (plan,) = plans_of(svc, who)
        assert plan.status == "active" and plan.external_ref.endswith(":PK:bachelor")
        assert [p["programme_ref"] for p in plan.contract["programmes"]] == ["pk-p1"]
        assert world == []  # an adult: no guardian mail

        # 2. the student withdraws consent: the same plan pauses, nothing is escalated
        out = data(post(client, params, "consent/withdraw"))
        assert out["choice"]["version"] == 2 and out["choice"]["consent"]["student"] == "missing"
        assert outbox(who) == [("delivered", None)] * 2  # delivered at once, not at the next sweep
        assert run_os(svc) == [("paused", "consent_missing")]
        (paused,) = plans_of(svc, who)
        assert (paused.id, paused.status) == (plan.id, "paused") and count(svc, models.support_cases) == 0
        assert events_of(svc, plan.id) == ["plan_paused"]

        # 3. the student gives consent again: the plan resumes, no second plan
        back = data(post(client, params, "consent/give", {"consent_version": "1"}))
        assert back["choice"]["version"] == 3 and back["choice"]["consent"]["student"] == "given"
        assert run_os(svc) == [("revised", None)]
        (resumed,) = plans_of(svc, who)
        assert (resumed.id, resumed.status) == (plan.id, "active")
        assert events_of(svc, plan.id) == ["plan_paused", "plan_resumed"]
        assert count(svc, models.counsellor_intake) == 3

        # the 5-minute sweep finds nothing left to send or to catch up on
        with who.factory() as db:
            assert bridge.sweep_once(db)["submitted"] == 0
        assert run_os(svc) == []
        assert_consistent(who.factory)  # the end-of-test check (R-04, R-05)


@pytest.mark.connect_row("6.15")
def test_an_under_18_student_is_held_until_the_guardian_agrees_and_paused_when_the_guardian_withdraws(svc, world):  # noqa: F811
    mails = world
    with student(dob="2012-05-05") as (client, who, params):
        # 4. the student chooses: their own consent is given, the guardian's is missing, so the OS holds it
        body = data(choose_with(client, params, destination="PK", places=PK_PLACE, intake=WINTER,
                                guardian_email=EMAIL))
        assert body["choice"]["consent"] == {"student": "given", "guardian": "missing"}
        assert body["guardian_email_sent"] is True and [m["to"] for m in mails] == [EMAIL]
        assert run_os(svc) == [("held", "consent_missing")]
        assert plans_of(svc, who) == [] and count(svc, models.support_cases) == 0

        # 5. the guardian opens the link (nothing changes), then agrees: the held decision becomes a plan
        agree_token = link_token(mails[0])
        for _ in range(2):  # a mail scanner opening the link
            assert public(client, "get", agree_token)["state"] == "ok"
        assert run_os(svc) == []
        assert public(client, "post", f"{agree_token}/agree") == {"state": "agreed", "confirmation_sent": True}
        assert run_os(svc) == [("planned", None)]
        (plan,) = plans_of(svc, who)
        assert plan.status == "active" and [p["programme_ref"] for p in plan.contract["programmes"]] == ["pk-p1"]

        # 6. the guardian withdraws with the link of the confirmation mail: the plan pauses
        assert len(mails) == 2
        withdraw_token = link_token(mails[1])
        assert public(client, "get", agree_token)["state"] == "used"
        page = public(client, "get", withdraw_token)  # the mail links to the same path; the token says its kind
        assert (page["state"], page["purpose"]) == ("ok", "withdraw") and page["text"]["withdraw_button"]
        assert public(client, "get", f"{withdraw_token}/withdraw")["text"] == page["text"] and run_os(svc) == []
        assert public(client, "post", f"{withdraw_token}/withdraw") == {"state": "withdrawn"}
        assert run_os(svc) == [("paused", "consent_missing")]
        (paused,) = plans_of(svc, who)
        assert (paused.id, paused.status) == (plan.id, "paused") and len(mails) == 3
        assert events_of(svc, plan.id) == ["plan_paused"]
        assert public(client, "post", f"{withdraw_token}/withdraw") == {"state": "used"}
        assert run_os(svc) == []
        with who.factory() as db:
            assert [c.outcome for c in db.scalars(select(GuardianConsent).order_by(GuardianConsent.created_at))] \
                == ["agreed", "withdrawn"]
        assert [r.decision_version for r in rows(who)] == [1, 2, 3]
        assert_consistent(who.factory)  # the end-of-test check (R-04, R-05)


@pytest.mark.connect_row("6.14")
def test_a_route_the_os_cannot_run_puts_nothing_in_the_os(svc, world):  # noqa: F811
    with student() as (client, who, params):
        with who.factory() as db:
            VaultService(db).apply_fact(who.workspace_id, "preferences.target_countries", ["United Kingdom"],
                                        "user_explicit")
            db.commit()
        options = data(client.get("/v1/roadmap/choice-options", params={**params, "field_key": FIELD},
                                  headers=TOKEN))
        assert {d["code"]: d["supported"] for d in options["destinations"]} == {"PK": True, "GB": False}
        # 7. a destination without a playbook: the choice is saved, PAI OS hears nothing
        body = data(choose_with(client, params, destination="GB", places=[], intake={"term": "autumn", "year": 2027}))
        assert body["choice"]["os_supported"] is False
        assert outbox(who) == [("not_sent", "not_supported")]
        assert run_os(svc) == []
        assert count(svc, models.counsellor_intake) == 0 and count(svc, PLAN) == 0
        assert count(svc, models.support_cases) == 0
        with who.factory() as db:
            assert bridge.sweep_once(db)["submitted"] == 0
        assert count(svc, models.counsellor_intake) == 0
        assert_consistent(who.factory)  # the end-of-test check (R-04, R-05)


def test_a_supported_choice_without_places_is_refused_so_a_later_withdrawal_still_pauses_the_plan(svc, world):  # noqa: F811
    """The final review's C1 sequence against a real PAI OS: a plan runs, a 0-place re-choice of a supported route,
    then a consent withdrawal. The re-choice is refused, so the withdrawal reaches the OS and the plan pauses."""
    with student() as (client, who, params):
        data(choose_with(client, params, destination="PK", places=PK_PLACE, intake=WINTER))
        assert run_os(svc) == [("planned", None)]
        (plan,) = plans_of(svc, who)
        refused = choose_with(client, params, destination="PK", places=[], intake=WINTER)
        assert refused.status_code == 422 and len(rows(who)) == 1
        data(post(client, params, "consent/withdraw"))
        assert outbox(who) == [("delivered", None)] * 2
        assert run_os(svc) == [("paused", "consent_missing")]
        (paused,) = plans_of(svc, who)
        assert (paused.id, paused.status) == (plan.id, "paused")
        assert_consistent(who.factory)  # the end-of-test check (R-04, R-05)


def test_with_the_flag_off_a_guardian_withdrawal_pauses_the_plan_once_the_flag_is_back(svc, world):  # noqa: F811
    mails = world
    with student(dob="2012-05-05") as (client, who, params):
        data(choose_with(client, params, destination="PK", places=PK_PLACE, intake=WINTER, guardian_email=EMAIL))
        public(client, "post", f"{link_token(mails[0])}/agree")
        assert run_os(svc)[-1] == ("planned", None)  # the older, held version is stale by then
        withdraw_token = link_token(mails[1])
        with patch.object(config, "CONNECT_HANDOFF", False, create=True):  # the flag rolled back: the plan still runs
            assert public(client, "post", f"{withdraw_token}/withdraw") == {"state": "withdrawn"}
            assert run_os(svc) == []
        with who.factory() as db:  # the flag is back: the sweep catches up
            assert bridge.sweep_once(db)["submitted"] == 1
        assert run_os(svc) == [("paused", "consent_missing")]
        assert [p.status for p in plans_of(svc, who)] == ["paused"]
        assert_consistent(who.factory)  # the flag is back and the sweep caught up: both sides agree (R-04, R-05)
