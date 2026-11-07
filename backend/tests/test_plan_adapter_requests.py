"""P1-T8 Task 6 (R-19, R-18): a plan step that waits for the student's data shows its request line and cannot be ticked
by hand; every other step is exactly as before (R-44). The bridge is stubbed: no OS runs here."""

import pytest

from app.pai_c.connect import request_texts
from app.pai_c.roadmap import plan_adapter
from tests.test_plan_adapter import STEP_KEYS, os_step, page, plan_client, tick, view_of

pytestmark = [pytest.mark.req("R-19"), pytest.mark.req("R-18")]


def request_step(task_id, template, ref, level, status="waiting_student", need_kind="fact"):
    key = f"{template}@{need_kind}:{ref}:{level}" if template != "result_expected" else f"result_expected@fact:{ref}"
    if template == "result_expected":  # the compiler's step: a PAI work step, no inbox kind, no needs
        return os_step(task_id, key, "A request", status, owner="pai", inbox_kind=None)
    return os_step(task_id, key, "A request", status, inbox_kind="provide",
                   needs=[{"kind": need_kind, "ref": ref, "evidence": level}])


STEPS = [
    request_step(1, "provide", "a.b", "stated"),
    request_step(2, "provide", "a.c", "shown"),
    request_step(3, "which_is_right", "a.d", "confirmed"),
    request_step(4, "result_expected", "a.e", None, "blocked"),
    request_step(5, "provide", "a.f", "stated", "done"),
    os_step(6, "gather@1", "Gather your documents", "waiting_student", inbox_kind="provide"),
]


def test_adapter_step_with_open_request_not_tickable():
    with plan_client(view_of(STEPS)) as (client, _, params, fake, _):
        steps = {s["key"]: s for s in page(client, params)["steps"]}
        assert steps["provide@fact:a.b:stated"]["tickable"] is False
        assert steps["which_is_right@fact:a.d:confirmed"]["tickable"] is False
        assert steps["gather@1"]["tickable"] is True  # a plain provide step is as before
        assert tick(client, params, "provide@fact:a.b:stated").status_code >= 400
        assert fake.completed == []


def test_adapter_adds_request_key_only_on_request_steps():
    with plan_client(view_of(STEPS)) as (client, _, params, _fake, _):
        steps = {s["key"]: s for s in page(client, params)["steps"]}
    assert steps["provide@fact:a.b:stated"]["request"] == {
        "kind": "provide", "evidence": "stated", "text": request_texts.text("provide_stated")}
    assert steps["provide@fact:a.c:shown"]["request"]["text"] == request_texts.text("provide_shown")
    assert steps["which_is_right@fact:a.d:confirmed"]["request"] == {
        "kind": "which_is_right", "evidence": "confirmed", "text": request_texts.text("which_is_right")}
    assert steps["result_expected@fact:a.e"]["request"] == {
        "kind": "result_expected", "text": request_texts.text("result_expected")}
    assert "request" not in steps["provide@fact:a.f:stated"]  # answered: no request any more
    assert "request" not in steps["gather@1"]
    assert set(steps["gather@1"]) >= STEP_KEYS and "request" not in steps["gather@1"]


def test_a_request_template_is_never_tickable_whatever_its_state():
    """M6: tickable follows the template, not only the request line."""
    for status in ("waiting_student", "pending", "ready"):
        step = request_step(1, "provide", "a.b", "stated", status)
        assert plan_adapter.steps_of(view_of([step]))[0]["tickable"] is False


def test_request_of_document_need_and_every_open_status():
    doc = plan_adapter.request_of(request_step(1, "provide", "hssc_certificate", "shown", need_kind="document"))
    assert doc == {"kind": "provide", "evidence": "shown", "text": request_texts.text("provide_shown")}
    for status in ("pending", "ready", "waiting_student", "blocked", "failed"):
        assert plan_adapter.request_of(request_step(1, "which_is_right", "a.b", "confirmed", status))["kind"] == "which_is_right"
    for status in ("done", "skipped", "cancelled"):
        assert plan_adapter.request_of(request_step(1, "which_is_right", "a.b", "confirmed", status)) is None
    assert plan_adapter.request_of(request_step(1, "result_expected", "a.e", None, "pending")) == {
        "kind": "result_expected", "text": request_texts.text("result_expected")}


def test_the_adapter_knows_the_templates_the_compiler_adds():
    """M5: the adapter cannot import app.os (tach), so its list is checked against the OS's here."""
    from app.os.requests import keys

    assert tuple(plan_adapter.REQUESTS) == tuple(keys.TEMPLATES)
