"""P1-T2 Task 6 (R-59): with every connection flag at its default the app behaves as before this branch. Choose and
withdraw answer with the same keys and values the roadmap API tests rely on (the response never shows the added
`decision_version`), the journey moves as before, no outbox row is written, and the sweep never touches PAI OS."""

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app import pai_os_bridge as bridge
from app.config import config
from app.models import OsOutbox, RouteDecision, StudentJourney
from app.os import ports
from app.os.ports import escalation as os_escalation
from app.os.ports import plan_source
from app.pai_c.connect.flags import PARTS
from tests.test_route_journey import TOKEN, choose, confirmed_student, stage, with_routes

pytestmark = pytest.mark.req("R-59")

CHOOSE_KEYS = {"id", "field_key", "possibility_id", "title", "chosen_at", "withdrawn_at", "steps", "time",
               "snapshot_steps", "steps_done", "route", "snapshot_verdict", "live_status"}


def test_every_connection_flag_defaults_to_off():
    assert PARTS and not any(getattr(config, name) for name in PARTS)


def outbox_count(db) -> int:
    db.expire_all()
    return len(db.scalars(select(OsOutbox)).all())


@pytest.mark.asyncio
@pytest.mark.req("R-79")
async def test_choose_and_withdraw_behave_as_before(monkeypatch):
    touched = MagicMock()  # any call into PAI OS lands here
    for module, names in ((plan_source, ("submit_decision", "latest_version", "supports", "counsellor_enabled")),
                          (os_escalation, ("pending_counsellor_escalations",))):
        for name in names:
            monkeypatch.setattr(module, name, getattr(touched, name))
    async with confirmed_student() as (client, student, db, journey_id):
        with_routes(student, db)
        first = choose(client, student, "electrical_engineering")
        assert set(first) == CHOOSE_KEYS and "decision_version" not in first
        assert (first["field_key"], first["withdrawn_at"], first["steps_done"]) == ("electrical_engineering", None, [])
        assert stage(db, journey_id) == "CHOSEN"
        journey = db.get(StudentJourney, journey_id)
        assert journey.current_objective == first["title"]
        assert journey.active_goal == {"route_decision_id": first["id"], "field_key": "electrical_engineering",
                                       "title": first["title"], "route": first["route"]}
        assert journey.decisions[-1]["kind"] == "route_choice"

        second = choose(client, student, "computer_engineering")  # choosing again withdraws the first
        db.expire_all()
        kinds = [(d["kind"], d["route_decision_id"]) for d in db.get(StudentJourney, journey_id).decisions]
        assert kinds[-3:] == [("route_choice", first["id"]), ("route_withdrawn", first["id"]),
                              ("route_choice", second["id"])]
        assert db.get(RouteDecision, first["id"]).withdrawn_at is not None

        response = client.post("/v1/roadmap/withdraw", params={"network": student.workspace_id}, headers=TOKEN)
        assert response.status_code == 200, response.text
        withdrawn = response.json()["data"]
        assert set(withdrawn) == CHOOSE_KEYS and withdrawn["id"] == second["id"]
        assert withdrawn["withdrawn_at"] is not None
        assert stage(db, journey_id) == "PROPOSED"
        journey = db.get(StudentJourney, journey_id)
        assert journey.active_goal is None and journey.current_objective is None
        assert journey.decisions[-1]["kind"] == "route_withdrawn" and journey.decisions[-1]["route_decision_id"] == second["id"]

        # Final review I4: the student's data export tells each withdrawal from a choice (status, version).
        from app.pai_c.data_export import export_student_data
        exported = export_student_data(db, student.workspace_id)["route_decisions"]
        assert [(d["decision_version"], d["status"], d["field_key"]) for d in exported] == [
            (1, "chosen", "electrical_engineering"), (2, "chosen", "computer_engineering"),
            (3, "withdrawn", "computer_engineering")]
        assert exported[0]["id"] == first["id"] and exported[1]["id"] == second["id"]
        assert exported[2]["steps_done"] == [] and exported[2]["chosen_at"] == exported[2]["withdrawn_at"]

        assert outbox_count(db) == 0  # nothing queued for PAI OS
        assert touched.mock_calls == []  # and nothing asked of it


@pytest.mark.asyncio
async def test_sweep_and_delivery_do_not_touch_the_os_ports(monkeypatch):
    touched = MagicMock()
    touched.pending.return_value = []
    monkeypatch.setattr(ports, "services", touched.services)
    monkeypatch.setattr(plan_source, "submit_decision", touched.submit_decision)
    monkeypatch.setattr(plan_source, "latest_version", touched.latest_version)
    monkeypatch.setattr(os_escalation, "pending_counsellor_escalations", touched.pending)
    async with confirmed_student() as (client, student, db, _j):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        assert bridge.deliver_pending(db) == {"delivered": 0, "failed": 0, "not_sent": 0}
        assert bridge.deliver_pending(db, student.workspace_id) == {"delivered": 0, "failed": 0, "not_sent": 0}
        got = bridge.sweep_once(db)  # flags off: decisions are left alone (escalation delivery is the old behaviour)
        assert got.get("submitted") == 0 and got.get("failed") == 0
        assert touched.submit_decision.mock_calls == [] and touched.latest_version.mock_calls == []
        assert outbox_count(db) == 0


@pytest.mark.asyncio
@pytest.mark.req("R-13")
async def test_student_facts_off_writes_no_version_no_outbox_and_asks_nothing_of_the_os(monkeypatch):
    from app.memory.candidates import MemoryCandidateService
    from app.memory.reconciler import MemoryReconciler
    from app.models import VaultVersion
    from app.os.ports import student_facts

    touched = MagicMock()
    touched.pending.return_value = []
    monkeypatch.setattr(ports, "services", touched.services)
    monkeypatch.setattr(plan_source, "counsellor_enabled", touched.counsellor_enabled)
    monkeypatch.setattr(student_facts, "record_event", touched.record_event)
    monkeypatch.setattr(student_facts, "latest_vault_version", touched.latest_vault_version)
    monkeypatch.setattr(os_escalation, "pending_counsellor_escalations", touched.pending)
    async with confirmed_student() as (_, student, db, _j):
        ws = student.workspace_id
        c = MemoryCandidateService(db).propose(
            ws, "vault_item", key="domicile", proposed_value={"province": "punjab"}, confidence=0.9,
            source_type="user_explicit", allow_user_explicit=True, input_channel="profile",
            evidence={"quote": "q", "capture": "details"})
        assert MemoryReconciler(db).reconcile(c).accepted
        db.commit()
        assert db.scalars(select(VaultVersion)).all() == [] and outbox_count(db) == 0
        bridge.sweep_once(db)
        assert touched.record_event.mock_calls == [] and touched.latest_vault_version.mock_calls == []
        assert touched.counsellor_enabled.mock_calls == []


@pytest.mark.req("R-01")
@pytest.mark.req("R-04")
@pytest.mark.req("R-44")
def test_roadmap_and_steps_are_byte_identical_to_the_pre_adapter_answers(monkeypatch):
    """P1-T5 Task 5: /v1/roadmap, /choose, /steps and /withdraw answer exactly as captured from the code before the
    plan adapter (tests/fixtures/connect/roadmap_pre_adapter.json), and nothing is asked of PAI OS."""
    import json
    from pathlib import Path

    from app.os.ports import plan_actions, plan_query
    from tests.roadmap_snapshots import walk

    touched = MagicMock()
    for module, names in ((plan_query, ("plan_view",)), (plan_actions, ("complete_step",)),
                          (plan_source, ("supports", "counsellor_enabled")), (ports, ("services",))):
        for name in names:
            monkeypatch.setattr(module, name, getattr(touched, name))
    monkeypatch.setattr(bridge, "plan_view", touched.bridge_plan_view)
    monkeypatch.setattr(bridge, "complete_step", touched.bridge_complete_step)
    expected = json.loads((Path(__file__).parent / "fixtures" / "connect" / "roadmap_pre_adapter.json").read_text())
    got = walk()
    assert sorted(got) == sorted(expected)
    for name in expected:
        assert got[name] == expected[name], name
    assert json.dumps(got, sort_keys=True) == json.dumps(expected, sort_keys=True)
    assert touched.mock_calls == []


@pytest.mark.req("R-04")
def test_flags_off_an_os_supported_row_ticks_locally_and_asks_nothing_of_the_os(monkeypatch):
    """Even a row marked os_supported answers from the Counsellor's own steps while the plan flag is off, and a
    token-only caller may tick: no plan view, no step completion, no account check."""
    from app.os.ports import plan_actions, plan_query
    from tests.test_roadmap_api import data, pre_eng

    touched = MagicMock()
    monkeypatch.setattr(plan_query, "plan_view", touched.plan_view)
    monkeypatch.setattr(plan_actions, "complete_step", touched.complete_step)
    monkeypatch.setattr(bridge, "plan_view", touched.bridge_plan_view)
    monkeypatch.setattr(bridge, "complete_step", touched.bridge_complete_step)
    monkeypatch.setattr(bridge, "counsellor_module_on", touched.module_on)
    with pre_eng() as (client, student, params):
        choose_answer = client.post("/v1/roadmap/choose", params=params, headers=TOKEN,
                                    json={"field_key": "electrical_engineering"})
        assert choose_answer.status_code == 200
        with student.factory() as db:
            db.query(RouteDecision).one().os_supported = True
            db.commit()
        ticked = data(client.post("/v1/roadmap/steps", params=params, headers=TOKEN,
                                  json={"key": "apply", "done": True}))
        page = data(client.get("/v1/roadmap", params=params, headers=TOKEN))["chosen"]
    assert ticked["steps_done"] == ["apply"] == page["steps_done"]
    assert set(ticked) == CHOOSE_KEYS and set(page) == CHOOSE_KEYS
    assert touched.mock_calls == []


@pytest.mark.asyncio
@pytest.mark.req("R-07")
async def test_t6_sweep_and_roadmap_unchanged(monkeypatch):
    """P1-T6 Task 3: with the hand-off off the sweep delivers no choice request and reports the same counts as before
    this task (the dict below was captured from the code before it), the pending request rows are not read, and the
    /v1/roadmap bodies equal the captured fixture."""
    import json
    from pathlib import Path

    from app.os.ports import choice_requests
    from tests.roadmap_snapshots import walk

    touched = MagicMock()
    touched.pending.return_value = []
    monkeypatch.setattr(ports, "services", touched.services)
    monkeypatch.setattr(choice_requests, "pending", touched.choice_pending)
    monkeypatch.setattr(choice_requests, "mark_delivery", touched.mark_delivery)
    monkeypatch.setattr(plan_source, "submit_decision", touched.submit_decision)
    monkeypatch.setattr(os_escalation, "pending_counsellor_escalations", touched.pending)
    async with confirmed_student() as (client, student, db, _j):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        got = bridge.sweep_once(db)
        assert got == {"submitted": 0, "failed": 0, "sent": 0, "refused": 0, "waiting": 0}
        assert bridge.deliver_choice_requests(db) == {"written": 0, "duplicate": 0, "stale": 0, "refused": 0,
                                                      "failed": 0, "skipped": 0}
        assert touched.choice_pending.mock_calls == [] and touched.mark_delivery.mock_calls == []
        assert touched.submit_decision.mock_calls == [] and outbox_count(db) == 0
    expected = json.loads((Path(__file__).parent / "fixtures" / "connect" / "roadmap_pre_adapter.json").read_text())
    walked = walk()
    assert json.dumps(walked, sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.req("R-11")
def test_t6_roadmap_paused_unchanged():
    """P1-T6 Task 4: with the plan-view flag on and the hand-off off, a paused plan's body carries no `reason_text`,
    even in rehearsal and with an escalation reason code."""
    from unittest.mock import patch

    from tests.test_plan_adapter import STEPS, page, plan_client, view_of

    for reason in ("not_eligible", "other", "consent_missing"):
        with patch.object(config, "CONNECT_HANDOFF", False, create=True), \
                patch.object(config, "CONNECT_CONSENT_DRAFT", True), \
                plan_client(view_of(STEPS, state="paused", reason=reason)) as (client, _, params, _f, _):
            plan = page(client, params)["plan"]
        assert set(plan) == {"state", "state_reason", "revision", "decision_version", "proposals_waiting", "changes"}
        assert plan["state_reason"] == reason


@pytest.mark.asyncio
@pytest.mark.req("R-08")
async def test_t6_no_adoption_route_effect(monkeypatch):
    """P1-T6 Task 6: with the hand-off or My plan part off, the adoption offer is `{offer: false}` and the agreement is
    refused with today's hand-off message, and PAI OS is asked nothing; the roadmap bodies equal the captured fixture."""
    import json
    from pathlib import Path
    from unittest.mock import patch

    from tests.roadmap_snapshots import walk

    touched = MagicMock()
    monkeypatch.setattr(bridge, "self_serve_plan", touched.self_serve_plan)
    monkeypatch.setattr(bridge, "request_adoption", touched.request_adoption)
    monkeypatch.setattr(plan_source, "request_adoption", touched.port_request_adoption)
    async with confirmed_student() as (client, student, db, _j):
        with_routes(student, db)
        choose(client, student, "electrical_engineering")
        params = {"network": student.workspace_id}
        with patch.object(config, "CONNECT_MY_PLAN", True, create=True):  # My plan on, hand-off off
            got = client.get("/v1/roadmap/adoption", params=params, headers=TOKEN)
            assert got.status_code == 200 and got.json()["data"] == {"offer": False}
        for handoff in (False, True):  # hand-off on but My plan off: no offer either
            with patch.object(config, "CONNECT_HANDOFF", handoff, create=True), \
                    patch.object(config, "CONNECT_MY_PLAN", False, create=True):
                assert client.get("/v1/roadmap/adoption", params=params, headers=TOKEN).json()["data"] == {
                    "offer": False}
        posted = client.post("/v1/roadmap/adoption", params=params, headers=TOKEN, json={"plan_id": 1})
        assert posted.status_code == 409 and posted.json() == {"detail": "The connection to PAI OS is not on"}
        assert touched.mock_calls == [] and outbox_count(db) == 0
    expected = json.loads((Path(__file__).parent / "fixtures" / "connect" / "roadmap_pre_adapter.json").read_text())
    assert json.dumps(walk(), sort_keys=True) == json.dumps(expected, sort_keys=True)


@pytest.mark.req("R-01")
def test_t7_upload_responses_unchanged(tmp_path, monkeypatch):
    """P1-T7: with CONNECT_ONE_UPLOAD off every upload, file and delete route answers as it did before the branch (the
    fixtures were captured from the code before the change; ids and times are masked). A `doc_type` field is ignored,
    no PAI OS document function is called, and the parse job is still followed by an extract job."""
    import json
    from pathlib import Path

    from tests.one_upload_support import jobs, masked, post_base64, post_file, post_folder, run_parse_job, upload_world

    def boom(*args, **kwargs):
        raise AssertionError("a PAI OS document function was called while the part is off")

    for name in ("document_file_bytes", "register_os_document", "forget_os_document", "document_types",
                 "on_os_document_deleted", "documents_enabled"):
        monkeypatch.setattr(bridge, name, boom)
    expected = json.loads((Path(__file__).parent / "fixtures" / "connect" / "t7_upload_responses_before.json").read_text())
    got = {}
    with upload_world(tmp_path) as (client, student, auth):
        plain = post_file(client, student, auth)
        got["post_plain"] = masked(plain)
        got["post_typed"] = masked(post_file(client, student, auth, name="typed.pdf", doc_type="transcript"))
        got["folder_plain"] = masked(post_folder(client, student, auth, name="a.pdf"))
        got["folder_typed"] = masked(post_folder(client, student, auth, name="b.pdf", doc_type="transcript"))
        got["base64"] = masked(post_base64(client, student, auth))
        first = post_file(client, student, auth, name="del.pdf").json()["data"]["id"]
        got["delete"] = masked(client.delete(f"/v1/files/{first}", headers=auth))
        second = post_file(client, student, auth, name="trash.pdf").json()["data"]["id"]
        got["trash"] = masked(client.post("/v1/files/trash", headers=auth,
                                          json={"network": student.workspace_id, "file_ids": [second]}))
        assert got == expected
        assert all("os_document" not in json.dumps(v) for v in got.values())
        file_id = plain.json()["data"]["id"]
        assert all("extract" not in payload for _, payload in jobs(student, "document.parse"))
        assert run_parse_job(student, file_id)["parsed"] is True
        extract = [p for _, p in jobs(student, "document.extract") if p.get("file_id") == file_id]
        assert extract == [{"file_id": file_id}]  # today's job, unchanged


@pytest.mark.req("R-44")
@pytest.mark.req("R-19")
def test_t8_roadmap_and_inbox_unchanged():
    """P1-T8 Task 6: a plan with no request step (every plan while the needs part is off) answers exactly as before: no
    `request` key on any step, today's tick rule, and the roadmap bodies equal the fixture captured before the change."""
    import json
    from pathlib import Path

    from tests.roadmap_snapshots import walk
    from tests.test_plan_adapter import STEPS, page, plan_client, view_of

    with plan_client(view_of(STEPS)) as (client, _, params, _f, _):
        steps = page(client, params)["steps"]
    assert steps and all("request" not in s for s in steps)
    assert [s["tickable"] for s in steps] == [True, False, False, False, False]
    expected = json.loads((Path(__file__).parent / "fixtures" / "connect" / "roadmap_pre_adapter.json").read_text())
    assert json.dumps(walk(), sort_keys=True) == json.dumps(expected, sort_keys=True)
