"""P2-T3: the integrity checks (R-71) as pure functions. Fictional text."""

import ssl

import httpx
import pytest

from app.os.knowledge.sources.integrity import (
    Previous,
    check_page,
    is_tls_failure,
    load_config,
    similarity,
)

pytestmark = pytest.mark.req("R-71")
CLEAN = " ".join(f"word{i}" for i in range(60))
ON = lambda url: "own.test" in url


def codes(text, links=(), previous=None, cfg=None):
    return [f.code for f in check_page(text, list(links), ON, previous, cfg)]


def test_clean_page_passes():
    assert codes("Admissions open. Merit is based on marks.", [("https://own.test/a", "apply")]) == []


def test_spam_needs_two_distinct_terms_in_text_anchors_or_addresses():
    assert codes("Our casino of ideas") == []  # one stray word
    assert codes("online casino and betting odds") == ["spam"]
    assert codes("Welcome", [("https://x-casino.test/", "bonus"), ("https://y.test/betting-odds", "go")]) == ["spam"]
    assert codes("FREE   SPINS and Roulette") == ["spam"]
    assert codes("casinos and bettings") == []  # whole words only in text
    assert codes("کیسینو و جوا") == ["spam"]


def test_link_flood_is_relative_to_the_last_clean_snapshot():
    off = [(f"https://off{i}.test/", "x") for i in range(12)]
    own = [("https://own.test/p", "p")]
    assert codes("page", off + own) == []  # no previous snapshot: this read is the baseline (review C2)
    assert codes("page", off + own, previous=Previous("page", links_total=1, links_off_list=0)) == ["link_flood"]
    assert codes("page", off[:5] + own * 20) == []  # below the minimum count
    already = Previous("page", links_total=13, links_off_list=12)  # the page was always a link list
    assert codes("page", off + own, previous=already) == []


def test_wholesale_change_unless_a_notice_explains_it():
    prev = Previous(CLEAN, 0, 0)
    other = " ".join(f"other{i}" for i in range(60))
    assert codes(other, previous=prev) == ["wholesale_change"]
    assert codes("Notice: " + other, previous=prev) == []
    assert codes(CLEAN + " plus one line", previous=prev) == []
    assert codes(other, previous=Previous("short page", 0, 0)) == []  # short pages may change completely
    assert codes(CLEAN, previous=None) == []
    assert similarity("a b c d", "a b c d") == 1.0


def test_thresholds_come_from_the_data_file():
    cfg = {**load_config(), "spam": {**load_config()["spam"], "min_distinct_terms": 1}}
    assert codes("our casino", cfg=cfg) == ["spam"]


def test_tls_failure_is_found_in_the_exception_chain():
    inner = ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED: certificate has expired")
    err = httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED]")
    err.__cause__ = inner
    assert is_tls_failure(err)
    assert is_tls_failure(httpx.ConnectError("x: CERTIFICATE_VERIFY_FAILED"))
    assert not is_tls_failure(httpx.ConnectError("connection refused"))
