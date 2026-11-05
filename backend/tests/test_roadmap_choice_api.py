"""P1-T3 Task 4: the choice-with-details and consent HTTP API (R-10, R-79). PAI OS and the mail are stubbed;
fictional data."""

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.config import config
from app.models import GuardianConsent, OsOutbox, RouteDecision, VaultFact
from app.pai_c.connect import places
from app.services import auth_emails
from app.security import rate_limit
from tests.test_handoff_delivery import flag, os_stub  # noqa: F401 - the fixture is used by name
from tests.test_roadmap_api import TOKEN, data, pre_eng, roadmap_client, choose
from tests.test_roadmap_engine import add_education, add_path, field_title, fsc

pytestmark = [pytest.mark.req("R-10"), pytest.mark.req("R-79")]

ROUTES = [{"key": "gb_bachelor", "origin": "PK", "destination": "GB", "level": "bachelor", "intake_terms": ["autumn"]}]
LIST = [{"ref": "uni-a:cs", "name": "Computing", "university": "Uni A"},
        {"ref": "uni-b:ee", "name": "Electrical", "university": "Uni B"}]
EMAIL = "parent.person@example.org"
FIELD = "electrical_engineering"


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    rate_limit.reset()
    sent = []
    monkeypatch.setattr(auth_emails, "send_email",
                        lambda to, subject, html, text_body=None: sent.append({"to": to, "text": text_body}) or True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    with patch("app.pai_os_bridge.list_routes", return_value=ROUTES), \
         patch("app.pai_os_bridge.programmes_for", return_value=LIST), \
         patch("app.pai_os_bridge.route_supported", return_value=True):
        yield sent
    rate_limit.reset()


def vault(client_ctx, dob="2000-01-01", country="Pakistan"):
    """Put the date of birth and country in the student's Vault."""
    client, student, params = client_ctx
    from app.memory.vault import VaultService
    with student.factory() as db:
        if dob:
            VaultService(db).apply_fact(student.workspace_id, "identity.date_of_birth", dob, "user_explicit")
        if country:
            VaultService(db).apply_fact(student.workspace_id, "location.current_country", country, "user_explicit")
        db.commit()


def details(**over):
    body = {"destination": "GB", "places": [{"ref": "uni-a:cs", "rank": 1}], "intake": {"term": "autumn", "year": 2027},
            "consent": True}
    body.update(over)
    return body


def post(client, params, path, body=None):
    return client.post(f"/v1/roadmap/{path}", params=params, headers=TOKEN, json=body)


def choose_with(client, params, **over):
    return post(client, params, "choose", {"field_key": FIELD, "details": details(**over)})


def rows(student, model=RouteDecision, **where):
    with student.factory() as db:
        return list(db.scalars(select(model).order_by(*([model.decision_version] if model is RouteDecision
                                                        else [model.created_at]))))


def test_old_body_works_with_the_flag_on_and_off(os_stub):
    for value in (False, True):
        with pre_eng() as (client, student, params), flag(value):
            body = data(choose(client, params, FIELD))
            assert body["field_key"] == FIELD
            assert ("choice" in body) is value  # flag off: exactly today's shape
            assert rows(student)[0].places in (None, [])


def test_choice_options_flag_off_says_so():
    with pre_eng() as (client, student, params), flag(False):
        got = data(client.get("/v1/roadmap/choice-options", params={**params, "field_key": FIELD}, headers=TOKEN))
        assert got == {"handoff": False}


def test_choice_options_flag_on(os_stub):
    ctx = pre_eng()
    with ctx as (client, student, params), flag(True):
        vault((client, student, params), dob=None)
        got = data(client.get("/v1/roadmap/choice-options", params={**params, "field_key": FIELD}, headers=TOKEN))
        assert got["handoff"] is True and got["needs_dob"] is True
        assert got["consent_version"] == "1" and got["consent_text"]["title"]
        assert {d["code"]: d["supported"] for d in got["destinations"]} == {"PK": False, "GB": True}
        assert got["level"] == "bachelor" and got["origin"] == "PK"
        vault((client, student, params), country=None)
        got = data(client.get("/v1/roadmap/choice-options", params={**params, "field_key": FIELD}, headers=TOKEN))
        assert got["needs_dob"] is False


def test_places_endpoint(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params))
        got = data(client.get("/v1/roadmap/places", headers=TOKEN,
                              params={**params, "destination": "GB", "level": "bachelor", "term": "autumn",
                                      "year": 2027}))
        assert [p["ref"] for p in got["places"]] == ["uni-a:cs", "uni-b:ee"]
        bad = client.get("/v1/roadmap/places", headers=TOKEN, params={
            **params, "destination": "gb", "level": "bachelor", "term": "autumn", "year": 2027})
        assert bad.status_code == 422


def test_details_with_consent_make_a_pending_version(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params))
        body = data(choose_with(client, params))
        choice = body["choice"]
        assert choice["version"] == 1 and choice["destination"] == "GB" and choice["level"] == "bachelor"
        assert choice["places"] == [{"programme_ref": "uni-a:cs", "rank": 1}]
        assert choice["intake"] == {"term": "autumn", "year": 2027} and choice["os_supported"] is True
        assert choice["consent"] == {"student": "given", "guardian": "not_needed"}
        (row,) = rows(student)
        assert row.origin_country == "PK" and row.authorized_at is not None and row.guardian_required is False
        assert os_stub["submitted"] and os_stub["submitted"][0]["authorized_at"]
        with student.factory() as db:
            assert [o.status for o in db.scalars(select(OsOutbox))] == ["delivered"]
        assert not rows(student, GuardianConsent)


def test_under_18_needs_a_guardian_email(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params), dob="2012-05-05")
        refused = choose_with(client, params)
        assert refused.status_code == 422 and not rows(student)
        bad = choose_with(client, params, guardian_email="not-an-email")
        assert bad.status_code == 422 and not rows(student)
        body = data(choose_with(client, params, guardian_email=EMAIL))
        assert body["choice"]["consent"] == {"student": "given", "guardian": "missing"}
        assert rows(student)[0].guardian_required is True
        assert len(stubs) == 1 and stubs[0]["to"] == EMAIL
        (consent,) = rows(student, GuardianConsent)
        assert consent.purpose == "agree" and EMAIL not in str(body)
        assert os_stub["submitted"][0]["guardian_required"] is True
        assert os_stub["submitted"][0]["guardian_authorized_at"] is None


def test_a_missing_dob_is_written_to_the_vault_as_stated(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params), dob=None)
        no_dob = choose_with(client, params)
        assert no_dob.status_code == 422 and not rows(student)
        body = data(choose_with(client, params, date_of_birth="2005-02-03"))
        assert body["choice"]["consent"]["student"] == "given"
        with student.factory() as db:
            fact = db.scalar(select(VaultFact).where(VaultFact.field_key == "identity.date_of_birth"))
            assert fact is not None and "2005-02-03" in str(fact.value)
            assert fact.status == "active" and fact.source_type == "user_explicit"


def test_an_existing_dob_is_never_rewritten(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params), dob="2012-05-05")
        data(choose_with(client, params, date_of_birth="1990-01-01", guardian_email=EMAIL))
        with student.factory() as db:
            values = [str(f.value) for f in db.scalars(select(VaultFact).where(
                VaultFact.field_key == "identity.date_of_birth"))]
        assert values and all("1990" not in v for v in values) and any("2012-05-05" in v for v in values)
        assert rows(student)[0].guardian_required is True  # the stored date decides


def test_consent_must_be_true_and_text_approved(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params))
        assert choose_with(client, params, consent=False).status_code == 422
        with patch("app.pai_c.connect.consent.texts", return_value={"approved": False, "version": "9"}):
            assert choose_with(client, params).status_code == 409
        assert not rows(student)


def test_bad_details_are_refused(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params))
        for over in ({"destination": "ZZ"}, {"intake": {"term": "monsoon", "year": 2027}},
                     {"intake": {"term": "autumn", "year": 2001}},
                     {"places": [{"ref": "not-offered", "rank": 1}]},
                     {"places": [{"ref": "uni-a:cs", "rank": 1}, {"ref": "uni-a:cs", "rank": 2}]},
                     {"places": [{"ref": "uni-a:cs", "rank": 2}]},
                     {"places": [{"ref": f"p{i}", "rank": i} for i in range(1, 7)]}):
            assert choose_with(client, params, **over).status_code == 422, over
        assert not rows(student)


def test_details_with_the_flag_off_are_refused():
    with pre_eng() as (client, student, params), flag(False):
        assert choose_with(client, params).status_code == 409
        assert not rows(student)


def test_withdraw_and_give_consent_make_new_versions(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params))
        data(choose_with(client, params))
        out = data(post(client, params, "consent/withdraw"))
        assert out["choice"]["consent"]["student"] == "missing" and out["choice"]["version"] == 2
        rs = rows(student)
        assert [r.decision_version for r in rs] == [1, 2] and rs[1].authorized_at is None
        assert rs[1].places == rs[0].places
        again = data(post(client, params, "consent/withdraw"))  # nothing to change: no new version
        assert again["choice"]["version"] == 2
        back = data(post(client, params, "consent/give"))
        assert back["choice"]["consent"]["student"] == "given" and back["choice"]["version"] == 3
        with patch("app.pai_c.connect.consent.texts", return_value={"approved": False, "version": "9"}):
            data(post(client, params, "consent/withdraw"))  # withdrawing is never blocked
            assert post(client, params, "consent/give").status_code == 409


def test_consent_routes_need_a_route_and_the_flag(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        assert post(client, params, "consent/withdraw").status_code == 404
    with pre_eng() as (client, student, params), flag(False):
        assert post(client, params, "consent/withdraw").status_code == 409
        assert post(client, params, "consent/give").status_code == 409
        assert post(client, params, "guardian/resend", {}).status_code == 409


def test_resend_uses_the_address_on_file_or_a_new_one(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params), dob="2012-05-05")
        assert post(client, params, "guardian/resend", {}).status_code == 404  # no route yet
        data(choose_with(client, params, guardian_email=EMAIL))
        with patch("app.pai_c.connect.guardian.rate_limit.allow", return_value=True):
            out = data(post(client, params, "guardian/resend", {}))
            assert out["sent"] is True and EMAIL not in str(out)
            assert [m["to"] for m in stubs] == [EMAIL, EMAIL]
            other = "other.parent@example.org"
            data(post(client, params, "guardian/resend", {"guardian_email": other}))
            assert stubs[-1]["to"] == other
            post(client, params, "consent/withdraw")
            assert post(client, params, "guardian/resend", {}).status_code == 409  # own consent first


def test_resend_is_rate_limited(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params), dob="2012-05-05")
        data(choose_with(client, params, guardian_email=EMAIL))
        assert post(client, params, "guardian/resend", {}).status_code == 429  # one a minute per address


def test_an_adult_needs_no_guardian_and_resend_says_so(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params))
        data(choose_with(client, params, guardian_email=EMAIL))  # ignored
        assert not rows(student, GuardianConsent)
        assert post(client, params, "guardian/resend", {"guardian_email": EMAIL}).status_code == 409


def test_a_dob_the_vault_did_not_save_is_refused_and_the_typed_date_is_not_trusted(os_stub):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params), dob=None)
        in_question = {"code": 0, "message": "ok", "data": {"saved": False, "in_question": True}}
        with patch("app.routers.vault._write", return_value=in_question):
            refused = choose_with(client, params, date_of_birth="1990-01-01")  # an adult date typed on the screen
        assert refused.status_code == 409 and "Vault" in refused.json()["detail"]
        assert not rows(student)
        saved_but_not_readable = {"code": 0, "message": "ok", "data": {"saved": True}}
        with patch("app.routers.vault._write", return_value=saved_but_not_readable):
            assert choose_with(client, params, date_of_birth="1990-01-01").status_code == 409
        assert not rows(student)


def test_an_unreadable_stored_dob_counts_as_under_18(os_stub, stubs):
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params), country="Pakistan", dob=None)
        real = places.vault_value
        patched = lambda db, ws, key: "not-a-date" if key == "identity.date_of_birth" else real(db, ws, key)  # noqa: E731
        with patch.object(places, "vault_value", patched):
            got = data(client.get("/v1/roadmap/choice-options", params={**params, "field_key": FIELD}, headers=TOKEN))
            assert got["needs_dob"] is False  # there is a date; it just cannot be read
            assert choose_with(client, params).status_code == 422  # the guardian path, not a dead end
            body = data(choose_with(client, params, guardian_email=EMAIL))
        assert body["choice"]["consent"]["guardian"] == "missing" and rows(student)[0].guardian_required is True


@pytest.mark.parametrize("failure", ["request_error", "text", "transport"])
def test_a_guardian_mail_problem_after_the_choice_is_not_a_500(os_stub, caplog, failure):
    from app.pai_c.connect import guardian
    from app.pai_c.connect.consent import ConsentTextNotApproved
    error = {"request_error": guardian.GuardianRequestError("x"), "text": ConsentTextNotApproved("x"),
             "transport": RuntimeError(f"smtp down for {EMAIL}")}[failure]
    with pre_eng() as (client, student, params), flag(True):
        vault((client, student, params), dob="2012-05-05")
        with patch.object(guardian, "request", side_effect=error):
            body = data(choose_with(client, params, guardian_email=EMAIL))
        assert body["guardian_email_sent"] is False and body["choice"]["version"] == 1
        assert len(rows(student)) == 1
        logged = "\n".join(r.getMessage() for r in caplog.records)
        assert EMAIL not in logged and "smtp down" not in logged
