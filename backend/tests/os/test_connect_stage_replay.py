"""P1-T10 Task C2 (R-46, R-44, R-45): the stage A-I replay with the connection off and on. Recorded model outputs, no
network call, fictional students. The Counsellor's model inputs, replies, actions and chat rows are identical off and
on after masking ids, times and fact values; screens may only gain keys. Real PAI OS on Postgres for the `on` run."""

import copy
import os
import socket
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import pai_os_bridge as bridge
from app.config import config
from app.os import ports
from app.os.adapters.counsellor import manifest
from app.pai_c.connect import places
from app.security import rate_limit
from app.services import auth_emails
from scripts import connect_stage_replay as replay
from tests.os.test_connect_t5_flow import level, run_os
from tests.os.test_counsellor_intake_v2 import svc  # noqa: F401 - the fixture is used by name

pytestmark = [pytest.mark.req("R-46"), pytest.mark.req("R-44"), pytest.mark.req("R-45")]

# What the connection adds to a screen the Counsellor already serves, per stage: new keys only (R-44 keeps every
# existing key and type). Anything outside this set fails the test.
STEP_ADDS = {"due_at", "due_tz", "estimated", "owner", "provisional", "title"}  # an OS step also carries these
ADDITIONS = {
    "I.screens.choose_response": {"choice", "plan"},
    "I.screens.decision_record": {"plan"},
    "I.screens.decision_record.steps[]": STEP_ADDS,
    "I.screens.roadmap.chosen": {"choice", "plan"},
    "I.screens.roadmap.chosen.steps[]": STEP_ADDS,
}


class OsWorld:
    """The live OS for the `on` run: after a choice, the OS intake runs and its events are delivered."""

    def __init__(self, svc):  # noqa: F811
        self.svc = svc

    def settle(self, student) -> None:
        run_os(self.svc)
        with student.factory() as db:
            bridge.deliver_os_events(db)


@contextmanager
def os_on(svc, monkeypatch):  # noqa: F811
    manifest.set_enabled(svc.engine, "pai", True)
    ports.configure(svc)
    rate_limit.reset()
    monkeypatch.setattr(auth_emails, "send_email", lambda to, subject, html, text_body=None: True)
    monkeypatch.setattr(config, "APP_URL", "https://app.example.test")
    try:
        yield OsWorld(svc)
    finally:
        manifest.set_enabled(svc.engine, "pai", False)
        ports.configure(None)
        rate_limit.reset()


def level_for(student_id):
    return lambda name: level(name)


def both(svc, monkeypatch, student_id):  # noqa: F811
    off = replay.run("off", student_id, level_patch=level)
    with os_on(svc, monkeypatch) as world:
        on = replay.run("on", student_id, os_world=world, level_patch=level)
    return off, on


@pytest.mark.parametrize("student_id", replay.STUDENTS)
def test_stage_a_to_i_inputs_and_replies_identical_off_and_on(svc, monkeypatch, student_id):  # noqa: F811
    off, on = both(svc, monkeypatch, student_id)
    assert set(off) == set(on) == set(replay.STAGES)
    assert all(off[s]["calls"] for s in replay.STAGES)  # every stage ran its recorded turns
    result = replay.diff(off, on)
    assert result["differences"] == []
    for added in result["screen_additions"]:
        where, _, key = added.rpartition(".")
        assert key in ADDITIONS.get(where, set()), f"an undocumented key the connection adds to a screen: {added}"
    assert {a for a in result["screen_additions"]}, "the on run must show the plan (the OS really ran)"


def test_normaliser_masks_only_values():
    entry = {"field_key": "identity.date_of_birth", "value": "2000-01-01", "status": "active"}
    other = {"field_key": "identity.date_of_birth", "value": "1999-12-31", "status": "active"}
    assert replay.normalise(entry) == replay.normalise(other)  # a fact value is masked
    ids = {"id": "6f9619ff-8b86-d011-b42d-00c04fc964ff", "at": "2027-01-02T03:04:05+00:00", "n": 1767225600000}
    again = {"id": "11111111-2222-3333-4444-555555555555", "at": "2028-02-03T04:05:06Z", "n": 1767225700000}
    assert replay.normalise(ids) == replay.normalise(again)  # ids and times are masked
    assert replay.normalise({"title": "one"}) != replay.normalise({"title": "two"})  # a text is not


def _stage(calls, screens=None):
    return {"calls": calls, "turns": [], "notebook": None, "screens": screens or {},
            "counts": {"events": 1, "turn_decisions": 1, "notifications": 0}}


def test_a_planted_structural_change_is_reported():
    call = {"phase": "counselor", "input": {"messages": [{"role": "user", "content": "<journey>{}</journey>"}]},
            "output": "{}"}
    off = {"A": _stage([call])}
    # a new context section the OS would add
    changed = copy.deepcopy(call)
    changed["input"]["messages"][0]["content"] += "<plan>{}</plan>"
    assert replay.diff(off, {"A": _stage([changed])})["differences"]
    # a new key in a message
    extra = copy.deepcopy(call)
    extra["input"]["messages"].append({"role": "system", "content": "x"})
    assert replay.diff(off, {"A": _stage([extra])})["differences"]
    # a call added or dropped
    assert replay.diff(off, {"A": _stage([call, call])})["differences"]
    # a screen key removed, a type changed, and a screen key added (only the last is allowed to pass the diff)
    screens = {"roadmap": {"counts": {"open": 2}, "chosen": None}}
    assert replay.diff({"A": _stage([call], screens)},
                       {"A": _stage([call], {"roadmap": {"chosen": None}})})["differences"]
    assert replay.diff({"A": _stage([call], screens)},
                       {"A": _stage([call], {"roadmap": {"counts": {"open": "2"}, "chosen": None}})})["differences"]
    grew = replay.diff({"A": _stage([call], screens)},
                       {"A": _stage([call], {"roadmap": {"counts": {"open": 2}, "chosen": None, "new": 1}})})
    assert grew["differences"] == [] and grew["screen_additions"] == ["A.screens.roadmap.new"]


def test_replay_makes_no_network_call(svc, monkeypatch):  # noqa: F811
    tried = []
    real = socket.socket.connect

    def spy(self, address, *a, **k):
        tried.append(address)
        return real(self, address, *a, **k)

    # Postgres (the OS) is local; any other address is an outside call. The recorder blocks provider clients itself.
    monkeypatch.setattr(socket.socket, "connect", spy)
    off = replay.run("off", "germany_master", stages="AB", level_patch=level)
    assert off["A"]["calls"] and off["B"]["calls"]
    outside = [a for a in tried if not (isinstance(a, tuple) and a and a[0] in ("127.0.0.1", "localhost", "::1"))
               and not isinstance(a, (str, bytes))]
    assert outside == []


def test_the_os_adds_no_chat_message_in_on_mode(svc, monkeypatch):  # noqa: F811
    off, on = both(svc, monkeypatch, "germany_master")
    chat = lambda c: {k: v for k, v in c.items() if k != "notifications"}  # noqa: E731
    for stage in replay.STAGES:
        assert chat(off[stage]["counts"]) == chat(on[stage]["counts"]), stage
        if "counts_after_os" in on[stage]:
            assert chat(on[stage]["counts_after_os"]) == chat(off[stage]["counts"]), stage
    assert "counts_after_os" in on["I"]
    assert on["I"]["screens"]["choose_response"]["choice"]["os_supported"] is True  # the OS really ran


def _shown(stage):
    """What the docs keep of a stage: every call's phase, the SHA-256 of its masked input (the whole input is what is
    compared), the full masked input of the Counsellor's own call, its output, the replies, the notebook and the screen
    shapes."""
    import hashlib
    import json

    calls = []
    for call in replay.normalise(stage["calls"]):
        text = json.dumps(call["input"], sort_keys=True, ensure_ascii=False)
        calls.append({"phase": call["phase"], "input_sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "input_chars": len(text), "output": call["output"],
                      **({"input": call["input"]} if call["phase"] == "counselor" else {})})
    return {"calls": calls, "turns": replay.normalise(stage["turns"]), "notebook": replay.normalise(stage["notebook"]),
            "chat_rows": stage["counts"], "screens": replay.normalise(stage["screens"], structural=True)}


def test_write_report(svc, monkeypatch):  # noqa: F811
    """Writes the docs when CONNECT_REPLAY_OUT is set (the CLI sets it); otherwise it only builds the report."""
    import json

    results = {}
    for student_id in replay.STUDENTS:
        off, on = both(svc, monkeypatch, student_id)
        results[student_id] = {"off": off, "on": on}
        assert replay.diff(off, on)["differences"] == []
    text = replay.report_md(results)
    assert "Stage A-I replay" in text
    target = os.environ.get("CONNECT_REPLAY_OUT")
    if target:
        out = Path(target)
        out.mkdir(parents=True, exist_ok=True)
        for mode in ("off", "on"):
            payload = {sid: {st: _shown(data[mode][st]) for st in replay.STAGES} for sid, data in results.items()}
            (out / f"{mode}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n",
                                              encoding="utf-8")
        (out.parent / "stage-a-i.md").write_text(text, encoding="utf-8")
