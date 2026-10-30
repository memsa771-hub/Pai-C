"""Offline test of scripts/beta_smoke.py: the checks on fake responses, a whole
run against a fake stack (no network, no models), the cap stop and the report."""

from argparse import Namespace

from scripts import beta_smoke as smoke

BANNED = smoke.praise_words()
RU_REPLY = "Robot banana acha shauq hai. Aap ko circuits mein sab se zyada kya pasand hai?"
EN_REPLY = "Building robots tells me a lot about how you like to work. Which part do you enjoy most?"


# ---- checks -----------------------------------------------------------------

def test_reply_one_question_in_roman_urdu_passes():
    assert smoke.check_reply(RU_REPLY, {}, "roman_ur", BANNED) == (True, "")


def test_reply_next_step_counts_as_the_question():
    ok, _ = smoke.check_reply("Aap ke marks Lahore board ke hain. Apne budget ke baare mein batayein.",
                              {"next_step": "Apne budget ke baare mein batayein."}, "roman_ur", BANNED)
    assert ok


def test_reply_two_questions_praise_and_wrong_language_fail():
    ok, note = smoke.check_reply("Zabardast! Aap kya karte hain? Aur kya pasand hai?", {}, "roman_ur", BANNED)
    assert not ok and "2 questions" in note and "zabardast" in note
    ok, note = smoke.check_reply("آپ کیا کرتے ہیں؟", {}, "roman_ur", BANNED)
    assert not ok and "Arabic script" in note
    ok, note = smoke.check_reply("Aap ko kya pasand hai aur kaise kaam karte hain?", {}, "en", BANNED)
    assert not ok and "Roman Urdu words" in note
    assert smoke.check_reply(EN_REPLY, None, "en", BANNED) == (True, "")


def test_opening_names_education_and_ends_with_one_question():
    assert smoke.check_opening("Ali, aap FSc Pre-Engineering ke 2nd year mein hain. Aap ko kya pasand hai?", [])[0]
    ok, note = smoke.check_opening("Ali, welcome. What do you enjoy?", [])
    assert not ok and "Pre-Engineering" in note
    ok, note = smoke.check_opening("You study FSc (Pre-Engineering)? Tell me more.", [])
    assert not ok and "does not end" in note
    assert smoke.check_opening("You study Intermediate Engineering. What next?", ["Intermediate Engineering"])[0]


def _entry(display, badge="Stated"):
    return {"type": "x", "display": display, "badge": badge}


def _vault(entries, known=6):
    return {"details": {"about": {"entries": entries[:4]}}, "story": [{"entries": entries[4:]}],
            "completeness": {"known": known}}


def test_vault_check():
    good = [_entry(f"Entry {i}") for i in range(8)]
    assert smoke.check_vault(_vault(good))[0]
    ok, note = smoke.check_vault(_vault(good[:7] + [_entry("pre_engineering", badge=None)], known=4))
    assert not ok and "raw codes" in note and "no badge" in note and "known 4" in note
    assert "entries (< 8)" in smoke.check_vault(_vault(good[:3]))[1]


def _card(**over):
    card = {"ready": True, "text": {"sentences": ["You build robots."]}, "version": "v2",
            "areas": [{"key": "interests", "entries": [{"id": "a"}]}], "unknowns": []}
    return {**card, **over}


def test_mirror_check():
    assert smoke.check_mirror(_card(), "v1")[0]
    ok, note = smoke.check_mirror(_card(ready=False, text=None, areas=[]), "v2")
    assert not ok and all(w in note for w in ("not ready", "no text", "no area", "not redrawn"))


def test_paths_check_notes_absent_field_notes():
    path = {"title": "Electrical Engineering", "status": "suggested", "why": "You like circuits.",
            "evidence": [{"text": "circuits", "evidence_level": "stated"}]}
    ok, note = smoke.check_paths([path])
    assert ok and "(absent)" in note
    with_note = {**path, "evidence": path["evidence"] + [{"text": "fact", "evidence_level": "source"}]}
    assert "field notes cited: 1" in smoke.check_paths([with_note])[1]
    assert not smoke.check_paths([{**path, "evidence": [{"evidence_level": "source"}]}])[0]
    assert smoke.check_paths([]) == (False, "no paths")


def _roadmap(region="punjab", colour="green"):
    return {"rules_as_of": "2026-09", "fields": [{
        "title": "EE", "field_key": "electrical_engineering", "status": "open",
        "steps": [{"key": "apply", "kind": "apply", "colour": colour, "tickable": True}],
        "time": {"basis": [{"region": region}]}}], "chosen": None}


def test_roadmap_check():
    assert smoke.check_roadmap(_roadmap())[0]
    ok, note = smoke.check_roadmap(_roadmap(region="federal", colour=None))
    assert not ok and "lack punjab" in note and "without colour" in note


def test_about_check_reads_feature_names():
    words = smoke.about_words()
    assert {"Vault", "Mirror", "Roadmap"} <= set(words)
    assert smoke.check_about("Aap ki baatein Vault mein jati hain aur Roadmap dikhata hai.", words)[0]
    assert not smoke.check_about("PAI helps you.", words)[0]


# ---- a whole run against a fake stack ---------------------------------------

class Response:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


class FakeStack:
    """Answers the routes the smoke calls; PAI replies to each student message."""

    def __init__(self, reply=RU_REPLY, about="Aap ki baatein Vault mein rehti hain. Kya aur jaanna hai?"):
        self.events, self.reply, self.about, self.chosen, self.done = [], reply, about, None, []
        self.version = "v1"

    def _post(self, source, content, message_type="chat"):
        self.events.append({"id": f"e{len(self.events) + 1}", "source": source, "metadata": {},
                            "payload": {"content": content, "message_type": message_type}})
        return self.events[-1]

    def request(self, method, path, params=None, json=None, headers=None):
        ok = lambda data: Response({"code": 0, "message": "ok", "data": data})  # noqa: E731
        route = (method, path)
        if route == ("POST", "/v1/auth/session"):
            return ok({"user": {"email": "s@example.com"}})
        if route == ("POST", "/v1/workspaces"):
            return ok({"workspaceId": "w1", "token": "machine"})
        if route == ("GET", "/v1/vault/onboarding"):
            return ok({"required": True, "fields": [{"name": "group", "labels": {"pre_engineering": "Pre-Engineering"}}]})
        if route == ("POST", "/v1/vault/onboarding"):
            self._post("openagents:pai", "Ali, aap FSc Pre-Engineering ke 2nd year mein hain. Aap ko kya pasand hai?")
            self.version = "v2"
            return ok({"saved": ["education"], "rejected": {}, "completed": True})
        if route == ("GET", "/v1/events"):
            after = (params or {}).get("after")
            if params.get("sort") == "desc":
                return ok({"events": self.events[-1:], "newest_id": self.events[-1]["id"] if self.events else None})
            ids = [e["id"] for e in self.events]
            start = ids.index(after) + 1 if after in ids else 0
            return ok({"events": self.events[start:]})
        if route == ("POST", "/v1/events"):
            content = json["payload"]["content"]
            human = self._post("human:u1", content)
            self._post("openagents:pai", self.about if content in smoke.ABOUT.values() else self.reply)
            return ok({"id": human["id"]})
        if route == ("GET", "/v1/vault"):
            return ok(_vault([_entry(f"Entry {i}") for i in range(9)]))
        if route == ("GET", "/v1/counselor/summary"):
            return ok({"card": _card(version=self.version)})
        if route == ("GET", "/v1/counselor/possibilities"):
            return ok({"possibilities": [{"title": "EE", "status": "suggested", "why": "Circuits.",
                                          "evidence": [{"text": "circuits", "evidence_level": "stated"}]}]})
        if route == ("GET", "/v1/roadmap"):
            page = _roadmap()
            if self.chosen:
                page["chosen"] = {"field_key": self.chosen, "steps": page["fields"][0]["steps"]}
            return ok(page)
        if route == ("POST", "/v1/roadmap/choose"):
            self.chosen = json["field_key"]
            return ok({})
        if route == ("GET", "/v1/counselor/workspace"):
            return ok({"stage": "CHOSEN" if self.chosen else "DIRECTION"})
        if route == ("POST", "/v1/roadmap/steps"):
            self.done.append(json["key"])
            return ok({"steps_done": self.done})
        return Response({"detail": f"unrouted {route}"}, 404)


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def _args(**over):
    base = dict(language="roman_ur", base_url="http://fake", cap_usd=5.0, dry_run=False, token="tok",
                create_student=False, reply_timeout=30.0)
    return Namespace(**{**base, **over})


def _run(stack, spend=None, **over):
    clock = Clock()
    api = smoke.Api("http://fake", "tok", http=stack)
    return smoke.run_smoke(_args(**over), api=api, spend=spend, sleep=clock.sleep, clock=clock)


def _spend(values, cap=5.0):
    values = iter(values)
    last = {}

    def read():
        last["spent"] = next(values, last.get("spent", 0.0))
        return {"spent": last["spent"], "month": "2026-10", "stage": "ok", "by_role": {"counselor": last["spent"]},
                "roles": {"counselor": {"provider": "anthropic", "model": "claude-sonnet-5-5"}}}
    return smoke.Spend(read, cap, "fake")


def test_whole_run_passes_on_a_good_stack():
    stack = FakeStack()
    run = _run(stack, spend=_spend([1.0] + [1.1] * 40))
    assert run.passed, [(c.name, c.note) for c in run.checks if not c.ok]
    names = [c.name for c in run.checks]
    assert names[0] == "spend baseline" and "8c tick apply step" in names and names[-1] == "9 how does PAI work"
    assert sum(n.startswith("4.") for n in names) == 6
    assert stack.chosen == "electrical_engineering" and stack.done == ["apply"]
    assert run.roles["counselor"]["model"] == "claude-sonnet-5-5"
    assert abs(run.spend["final"] - run.spend["baseline"] - 0.1) < 1e-9


def test_bad_replies_are_defects_but_the_run_goes_on():
    run = _run(FakeStack(reply="Shabash! Kya aap ko robots pasand hain? Aur circuits?"), spend=_spend([0.0]))
    turns = [c for c in run.checks if c.name.startswith("4.")]
    assert len(turns) == 6 and not any(c.ok for c in turns)
    assert run.stopped is None and not run.passed


def test_cap_stops_the_run_after_the_step_that_crossed_it(tmp_path):
    # baseline 1.0; the opening leaves 1.5, the first turn 7.0 (> 5 over baseline)
    run = _run(FakeStack(), spend=_spend([1.0, 1.5, 7.0]))
    assert run.stopped and "cap" in run.stopped
    assert run.checks[-1].name == "spend cap" and not run.checks[-1].ok
    assert not any(c.name.startswith("4.2") for c in run.checks)
    report = smoke.write_report(run, tmp_path / "r.md")
    assert "spend cap | FAIL" in report and "stopped" in report


def test_missing_reply_is_a_hard_stop():
    stack = FakeStack()
    stack._post = lambda *a, **k: {"id": "x"}  # PAI never answers
    run = _run(stack)
    assert run.stopped and "no PAI reply" in run.stopped


def test_report_writer(tmp_path):
    run = smoke.Run("en", "http://fake", 5.0)
    run.checks = [smoke.Check("5 vault", True, 12, "9 entries"),
                  smoke.Check("7 paths | x", False, 30, "no paths", True)]
    run.student = {"email": "s@example.com", "workspace_id": "w1"}
    run.spend = {"source": "fake", "month": "2026-10", "stage": "ok", "baseline": 1.0, "final": 1.75,
                 "by_role_delta": {"counselor": 0.5, "analyst": 0.25}}
    run.roles = {"counselor": {"provider": "anthropic", "model": "claude-sonnet-5-5"}}
    run.transcript = [("Student", "hi"), ("PAI", "Hello. What do you study?")]
    path = tmp_path / "deep" / "report.md"
    text = smoke.write_report(run, path)
    assert path.read_text(encoding="utf-8") == text
    assert "| 1 | 5 vault | pass | 12 | 9 entries |" in text
    assert "7 paths \\| x | FAIL" in text
    assert "this run est_usd **$0.7500**" in text and "counselor: $0.5000" in text
    assert "| counselor | anthropic | claude-sonnet-5-5 |" in text
    assert "## Defects\n\n- 7 paths | x: no paths" in text
    assert "Result: FAIL" in text


def test_live_run_refuses_without_a_spend_source(capsys):
    import pytest
    with pytest.raises(SystemExit):
        smoke.main(["--token", "t"])
    assert "spend source" in capsys.readouterr().err


# ---- background settle ------------------------------------------------------

class Poller:
    """Fake background_jobs reader: busy for the first `busy_polls` reads."""

    def __init__(self, busy_polls, busy_type="memory.extract"):
        self.calls, self.busy_polls, self.busy_type = 0, busy_polls, busy_type

    def __call__(self, workspace):
        assert workspace == "w1"
        self.calls += 1
        rows = [{"type": "memory.embed", "status": "pending", "seconds": 1.0},
                {"type": "memory.extract", "status": "succeeded", "seconds": 12.0},
                {"type": "counselor.analyze", "status": "succeeded", "seconds": 30.0}]
        if self.calls <= self.busy_polls:
            rows.append({"type": self.busy_type, "status": "running", "seconds": 0.0})
        return rows


def test_wait_for_settle_polls_until_no_settle_job_is_busy():
    clock, poller = Clock(), Poller(3, "counselor.analyze")
    settled, waited, busy = smoke.wait_for_settle(poller, "w1", 120, sleep=clock.sleep, clock=clock)
    assert settled and busy == [] and waited == 15 and poller.calls == 4  # memory.embed is not waited for


def test_wait_for_settle_gives_up_at_the_timeout():
    clock = Clock()
    settled, waited, busy = smoke.wait_for_settle(Poller(10 ** 6), "w1", 12, sleep=clock.sleep, clock=clock)
    assert not settled and waited == 12 and busy == ["memory.extract"]


def test_run_waits_for_settle_before_vault_mirror_and_choose_and_reports_job_times(tmp_path):
    poller = Poller(2)
    clock = Clock()
    api = smoke.Api("http://fake", "tok", http=FakeStack())
    run = smoke.run_smoke(_args(), api=api, jobs=poller, sleep=clock.sleep, clock=clock)
    assert run.passed, [(c.name, c.note) for c in run.checks if not c.ok]
    notes = {c.name: c.note for c in run.checks}
    assert "settled in 10 s" in notes["5 vault"]
    assert "settled in 0 s" in notes["6 mirror ready, text, redrawn"]
    assert "settled in 0 s" in notes["8b choose -> CHOSEN"]
    report = smoke.write_report(run, tmp_path / "r.md")
    assert "## Latency" in report and "- 4.1 turn" in report
    assert "extractor (memory.extract) jobs: 1, median 12.0 s" in report
    assert "planner (counselor.analyze) jobs: 1, median 30.0 s" in report


def test_choose_is_skipped_as_a_defect_when_the_mirror_is_not_ready():
    stack = FakeStack()
    ready = {"n": 0}
    original = stack.request

    def request(method, path, **kw):
        response = original(method, path, **kw)
        if path == "/v1/counselor/summary":
            ready["n"] += 1
            if ready["n"] > 2:  # ready for the Mirror check, not when choosing
                response._data["data"]["card"]["ready"] = False
        return response
    stack.request = request
    run = _run(stack)
    choose = next(c for c in run.checks if c.name.startswith("8b"))
    assert not choose.ok and "skipped: Mirror not ready" in choose.note
    assert stack.chosen is None and not any(c.name.startswith("8c") for c in run.checks)
