"""Slice 9a Task 12: the billed rehearsal's start check (spec §2.7, S9-D9; plan ruling 5).

`--billed` refuses to start unless the OpenAI key is set and all four monthly caps are set and sum to at most $15.
These tests call the check only: no billed run is ever started from a test, and no real key is used (the value below
is a fictional placeholder)."""

import pytest

from tests.os.rehearsal.run import BILLED_TENANT, CAPS, BilledRefused, billed_env, main

FAKE_KEY = "fictional-not-a-key-123"  # a placeholder: never a real key
GOOD = {"OS_OPENAI_API_KEY": FAKE_KEY, "OS_RESEARCH_MONTHLY_USD": "5", "OS_DOCUMENTS_MONTHLY_USD": "4",
        "OS_STATEMENTS_MONTHLY_USD": "4", "OS_REPLAN_MONTHLY_USD": "2"}


def test_refuses_without_key():
    env = {k: v for k, v in GOOD.items() if k != "OS_OPENAI_API_KEY"}
    with pytest.raises(BilledRefused, match="OS_OPENAI_API_KEY"):
        billed_env(env)
    with pytest.raises(BilledRefused, match="OS_OPENAI_API_KEY"):
        billed_env({**GOOD, "OS_OPENAI_API_KEY": "  "})


@pytest.mark.parametrize("cap", CAPS)
def test_refuses_with_a_missing_cap(cap):
    env = {k: v for k, v in GOOD.items() if k != cap}
    with pytest.raises(BilledRefused, match=cap):
        billed_env(env)
    with pytest.raises(BilledRefused, match=cap):
        billed_env({**GOOD, cap: ""})


@pytest.mark.parametrize("bad", ["five", "-1", "nan", "inf"])
def test_refuses_a_cap_that_is_not_a_plain_amount(bad):
    with pytest.raises(BilledRefused, match="OS_REPLAN_MONTHLY_USD"):
        billed_env({**GOOD, "OS_REPLAN_MONTHLY_USD": bad})


def test_refuses_when_caps_sum_over_15():
    with pytest.raises(BilledRefused, match="15"):
        billed_env({**GOOD, "OS_RESEARCH_MONTHLY_USD": "5.01"})


def test_accepts_a_valid_env():
    out = billed_env(GOOD)
    assert out["OS_MODEL_MODE"] == "openai"
    assert out["OS_TENANT_ID"] == BILLED_TENANT == "rehearsal-billed"
    assert out["OS_REHEARSAL"] == "on"
    assert {k: out[k] for k in CAPS} == {k: GOOD[k] for k in CAPS}
    assert "OS_OPENAI_API_KEY" not in out  # the key stays in the process env; it is never copied or printed
    assert billed_env({**GOOD, "OS_RESEARCH_MONTHLY_USD": "4", "OS_REPLAN_MONTHLY_USD": "1.5"})  # under 15 is fine


def test_refusal_never_shows_the_key():
    env = {**GOOD, "OS_REPLAN_MONTHLY_USD": "9"}
    with pytest.raises(BilledRefused) as err:
        billed_env(env)
    assert FAKE_KEY not in str(err.value)


def test_cli_refuses_before_anything_starts(monkeypatch, capsys, tmp_path):
    """main() with --billed and no key exits 2 before touching the database or starting a worker."""
    for k in ("OS_OPENAI_API_KEY", *CAPS):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OS_RESEARCH_MONTHLY_USD", "5")

    def boom(*a, **kw):
        raise AssertionError("a billed rehearsal must not start")

    monkeypatch.setattr("tests.os.rehearsal.run.Rehearsal", boom)
    assert main(["--students", "S1", "--billed", "--out", str(tmp_path / "billed")]) == 2
    err = capsys.readouterr().err
    assert "refused" in err and "OS_OPENAI_API_KEY" in err


def test_driver_takes_the_billed_tenant(tmp_path):
    """The driver seeds and checks the billed tenant (the API and the worker get it from the same settings). Nothing
    starts: only the constructor runs."""
    from tests.os.rehearsal.driver import TENANT, Rehearsal

    url = "postgresql://unused@localhost/unused"
    assert Rehearsal(["S1"], tmp_path / "a", database_url=url).tenant == TENANT
    billed = Rehearsal(["S1", "S3", "S5"], tmp_path / "b", database_url=url, billed=billed_env(GOOD))
    assert billed.tenant == BILLED_TENANT
    assert FAKE_KEY not in repr(billed.billed)



# ---- the whole-run budget guard (Task 12 fix round 1). The spend query, the worker and the API are faked: no
# database, no worker, no billed run.

URL = "postgresql://unused@localhost/unused"


def _billed(tmp_path, spend=lambda: 0.0):
    from tests.os.rehearsal.driver import Rehearsal

    r = Rehearsal(["S1", "S3"], tmp_path / "billed", database_url=URL, billed=billed_env(GOOD))
    r._spent = spend
    return r


def test_guard_never_stops_an_offline_run(tmp_path):
    from tests.os.rehearsal.driver import Rehearsal

    offline = Rehearsal(["S1"], tmp_path / "a", database_url=URL)
    offline.settle_timed_out = True
    assert offline._billed_stop() is False


def test_guard_stops_at_a_margin_below_the_cap(tmp_path):
    r = _billed(tmp_path, lambda: 11.99)
    assert r.billed_total == 15.0 and r.billed_stop_at() == 12.0  # max($1, 20 %) below $15
    assert r._billed_stop() is False
    r._spent = lambda: 12.0
    assert r._billed_stop() is True
    assert r.billed_stopped and r.admin_actions == [f"billed_stop: {r.billed_stopped}"]
    assert r.failures.entries() == []  # a safety stop, not a product failure
    r._spent = lambda: 0.0
    assert r._billed_stop() is True  # latched: once stopped, stays stopped
    small = _billed(tmp_path / "s")
    small.billed_total = 2.0
    assert small.billed_stop_at() == 1.0  # at least $1 of margin


def test_guard_stops_when_a_wait_timed_out(tmp_path):
    r = _billed(tmp_path, lambda: 0.0)
    r.settle_timed_out = True  # what settle() sets on `worker_busy`: spend in flight unknown
    assert r._billed_stop() is True
    assert "busy" in r.billed_stopped


def test_guard_stops_when_the_spend_cannot_be_read(tmp_path):
    def broken():
        raise RuntimeError("database gone")

    r = _billed(tmp_path, broken)
    assert r._billed_stop() is True
    assert [f.id for f in r.failures.entries()] == ["billed_guard_error"]


class _Fake:
    """Replaces the driver's API, worker and clock calls for the loop tests."""

    def __init__(self, r, spend_after: list[float]):
        self.r, self.spend_after, self.settles, self.advances = r, spend_after, 0, 0
        r._act = lambda run: True  # every student always acts: the inner rounds keep going
        r._observe = lambda run, today: None
        r.settle = self.settle
        r.advance = self.advance
        r.tick = lambda: None
        r._spent = lambda: self.spend_after[min(self.settles, len(self.spend_after) - 1)]

    def settle(self):
        self.settles += 1

    def advance(self, days):
        self.advances += 1


def _runs(r):
    from tests.os.rehearsal.driver import Run, student_ref

    return [Run(s, student_ref(s.sid)) for s in r.students]


def test_loop_checks_after_every_settle_in_the_inner_rounds(tmp_path):
    r = _billed(tmp_path)
    fake = _Fake(r, [0.0, 13.0])  # over the stop point after the first wait
    r._loop(_runs(r))
    assert fake.settles == 1 and fake.advances == 0  # stopped right after that wait, before moving time


def test_loop_checks_after_tick_and_settle(tmp_path):
    r = _billed(tmp_path)
    fake = _Fake(r, [0.0, 13.0])
    r._act = lambda run: False  # nobody acts: straight to advance, tick, settle
    r._loop(_runs(r))
    assert fake.advances == 1 and fake.settles == 1 and r.billed_stopped


def test_final_after_a_guard_stop_logs_no_not_finished(tmp_path):
    r = _billed(tmp_path, lambda: 13.0)
    runs = _runs(r)
    for n, run in enumerate(runs, 1):
        run.plan_id = n
    assert r._billed_stop() is True
    r._check_events = lambda run: (_ for _ in ()).throw(AssertionError("no event check after a guard stop"))
    r.svc = type("Svc", (), {"kernel": type("K", (), {"changes_paused": staticmethod(lambda plan_id: False)})()})()
    r._integrity = lambda runs: None
    r._final(runs)
    assert {run.state for run in runs} == {"billed_stop"}
    assert r.failures.entries() == []


def test_settings_repr_hides_the_openai_key():
    from app.os.settings import load_settings

    s = load_settings({"OS_DATABASE_URL": "postgresql://a@b/c", "OS_OPENAI_API_KEY": FAKE_KEY})
    assert s.openai_api_key == FAKE_KEY and FAKE_KEY not in repr(s)


# ---- the connection preflight (final review fix pass). The HTTP call is faked: no test reaches the network.

class _Resp:
    def __init__(self, status_code: int):
        self.status_code = status_code


def _fake_get(answer):
    calls = []

    def get(url, **kw):
        calls.append((url, kw))
        if isinstance(answer, Exception):
            raise answer
        return answer

    return get, calls


def test_preflight_passes_on_2xx():
    from tests.os.rehearsal.run import preflight

    get, calls = _fake_get(_Resp(200))
    preflight(GOOD, get=get)
    [(url, kw)] = calls
    assert url == "https://api.openai.com/v1/models"
    assert kw["timeout"] == 10
    assert kw["headers"]["Authorization"] == f"Bearer {FAKE_KEY}"


@pytest.mark.parametrize("answer,said", [
    (_Resp(401), "HTTP 401"),
    (_Resp(503), "HTTP 503"),
])
def test_preflight_refuses_a_non_2xx_answer(answer, said):
    from tests.os.rehearsal.run import preflight

    get, _ = _fake_get(answer)
    with pytest.raises(BilledRefused, match=said) as err:
        preflight(GOOD, get=get)
    assert "api.openai.com" in str(err.value) and FAKE_KEY not in str(err.value)


def test_preflight_refuses_when_it_cannot_connect():
    """What the proxy did in the 2-hour run: CONNECT to api.openai.com refused (403). The reason names the host and
    the error type only, never the key (not even when the error's own text carries it)."""
    import httpx

    from tests.os.rehearsal.run import preflight

    get, _ = _fake_get(httpx.ProxyError(f"403 Forbidden for {FAKE_KEY}"))
    with pytest.raises(BilledRefused, match="ProxyError") as err:
        preflight(GOOD, get=get)
    assert "api.openai.com" in str(err.value) and FAKE_KEY not in str(err.value)
    assert err.value.__cause__ is None and err.value.__suppress_context__  # no traceback shows the error's text


def test_cli_refuses_when_the_preflight_fails(monkeypatch, capsys, tmp_path):
    """main() with --billed, a complete env and no route to OpenAI exits 2 before any rehearsal starts."""
    import httpx

    for k, v in GOOD.items():
        monkeypatch.setenv(k, v)

    def no_route(url, **kw):
        raise httpx.ConnectError("refused")

    def boom(*a, **kw):
        raise AssertionError("a billed rehearsal must not start")

    monkeypatch.setattr("tests.os.rehearsal.run.httpx.get", no_route)
    monkeypatch.setattr("tests.os.rehearsal.run.Rehearsal", boom)
    assert main(["--students", "S1", "--billed", "--out", str(tmp_path / "billed")]) == 2
    out = capsys.readouterr()
    assert "--billed refused: " in out.err and "api.openai.com" in out.err and "ConnectError" in out.err
    assert FAKE_KEY not in out.err + out.out
