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


def test_billed_run_stops_at_the_caps_sum(tmp_path, monkeypatch):
    """The caps are monthly on rehearsal time, so the driver also stops a billed run once the tenant's whole spend
    reaches the caps' sum. The spend query is replaced: nothing starts and no database is used."""
    from tests.os.rehearsal.driver import Rehearsal

    url = "postgresql://unused@localhost/unused"
    offline = Rehearsal(["S1"], tmp_path / "a", database_url=url)
    assert offline._budget_spent() is False  # never for an offline run
    billed = Rehearsal(["S1"], tmp_path / "b", database_url=url, billed=billed_env(GOOD))
    assert billed.billed_total == 15.0
    monkeypatch.setattr(billed, "_spent", lambda: 14.99)
    assert billed._budget_spent() is False and not billed.failures.entries()
    monkeypatch.setattr(billed, "_spent", lambda: 15.0)
    assert billed._budget_spent() is True
    assert [f.id for f in billed.failures.entries()] == ["billed_total_reached"]
