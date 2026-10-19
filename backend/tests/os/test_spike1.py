"""Spike 1 harness: page reading, trust checks, scoring, and one end-to-end run on a fake model.

No network and no paid model: httpx.MockTransport serves the pages, FunctionModel gives the readings.
"""
import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from spikes.spike1.fields import Found, German, English, match_key, scorable
from spikes.spike1.pages import Fetcher, collect, html_to_text, is_official, normalise, rank_links, Page
from spikes.spike1.programmes import Programme, load_key, load_programmes
from spikes.spike1.run import report, research
from spikes.spike1.score import score
from spikes.spike1.trust import Verdict, judge

UNI = "https://www.uni-x.de"
PROGRAMME_HTML = f"""<html><head><script>var x = "Deadline: 01 Jan";</script><style>p{{}}</style></head>
<body><h1>MSc Data</h1><p>The programme is taught in English.</p>
<p>Applicants with a foreign degree apply via uni-assist by 15 July 2026 for the winter semester 2026/27.</p>
<a href="/apply/deadlines">Application deadlines</a> <a href="https://elsewhere.com/apply">Apply elsewhere</a>
<a href="/news">News</a></body></html>"""
DEADLINES_HTML = "<p>Winter semester 2026/27: application period 1 April to 15 July.</p>"


def transport(pages: dict[str, tuple[int, str]], calls: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if calls is not None:
            calls.append(url)
        status, body = pages.get(url, (404, ""))
        return httpx.Response(status, text=body, headers={"content-type": "text/html"})
    return httpx.MockTransport(handler)


def fetcher(tmp_path: Path, pages: dict, calls: list | None = None) -> Fetcher:
    return Fetcher(tmp_path / "cache", httpx.Client(transport=transport(pages, calls), follow_redirects=True))


# --- pages ---------------------------------------------------------------------------------


def test_html_to_text_drops_scripts_and_resolves_links():
    text, links = html_to_text(PROGRAMME_HTML, UNI + "/msc-data")
    assert "taught in English" in text and "var x" not in text and "p{}" not in text
    assert (UNI + "/apply/deadlines", "Application deadlines") in links


def test_robots_disallow_blocks_and_cache_avoids_refetch(tmp_path):
    calls: list[str] = []
    pages = {UNI + "/robots.txt": (200, "User-agent: *\nDisallow: /private"),
             UNI + "/msc-data": (200, PROGRAMME_HTML)}
    f = fetcher(tmp_path, pages, calls)
    assert f.get(UNI + "/private/x").blocked == "robots"
    assert f.get(UNI + "/msc-data").ok
    n = len(calls)
    assert Fetcher(tmp_path / "cache", f.client).get(UNI + "/msc-data").ok and len(calls) == n


def test_robots_403_disallows_all(tmp_path):
    f = fetcher(tmp_path, {UNI + "/robots.txt": (403, ""), UNI + "/msc-data": (200, PROGRAMME_HTML)})
    assert f.get(UNI + "/msc-data").blocked == "robots"


def test_http_error_recorded_not_retried(tmp_path):
    calls: list[str] = []
    page = fetcher(tmp_path, {UNI + "/gone": (500, "")}, calls).get(UNI + "/gone")
    assert page.blocked == "http_500" and calls.count(UNI + "/gone") == 1


def test_official_domains():
    assert is_official("https://www2.daad.de/x", ("uni-x.de",))
    assert is_official("https://www.uni-assist.de/x", ())
    assert is_official("https://sub.uni-x.de/a", ("uni-x.de",))
    assert not is_official("https://www.mygermanuniversity.com/x", ("uni-x.de",))


def test_rank_links_official_topical_only():
    p = Page(url=UNI + "/msc-data", text="x", links=html_to_text(PROGRAMME_HTML, UNI + "/msc-data")[1])
    assert rank_links([p], ("uni-x.de",), seen=set()) == [UNI + "/apply/deadlines"]


def test_rank_links_skips_shared_hubs_portals_and_wrapped_urls():
    links = [("https://www.daad.de/en/studying-in-germany/requirements/application-process/", "Application process"),
             ("https://www.daad.de/en/report-an-accessibility-issue/?barrierUrl=https%3A%2F%2Fx", "Report"),
             ("https://campus.uni-x.de/qisserver/pages/cs/sys/portal/start.faces", "Apply online"),
             ("https://www.uni-x.de/go?url=https://elsewhere.com/apply", "Apply"),
             ("https://www.uni-x.de/en/master/data/admission", "Admission requirements")]
    p = Page(url="https://www2.daad.de/detail/1", text="x", links=links)
    assert rank_links([p], ("uni-x.de",), seen=set()) == ["https://www.uni-x.de/en/master/data/admission"]


def test_collect_follows_ranked_links(tmp_path):
    f = fetcher(tmp_path, {UNI + "/msc-data": (200, PROGRAMME_HTML), UNI + "/apply/deadlines": (200, DEADLINES_HTML)})
    pages = collect(f, [UNI + "/msc-data"], ("uni-x.de",))
    assert [p.url for p in pages] == [UNI + "/msc-data", UNI + "/apply/deadlines"] and all(p.ok for p in pages)


# --- trust ---------------------------------------------------------------------------------

PAGE_TEXT = {UNI + "/p": normalise("Applicants apply via uni-assist by 15 July 2026 for the winter semester 2026/27.")}


def fact(value, quote="apply via uni-assist by 15 July 2026", url=UNI + "/p", cycle="winter semester 2026/27"):
    return Found(value=value, quote=quote, url=url, cycle=cycle)


@pytest.mark.parametrize("a,b,field,min_cycle,status,reason", [
    (fact("07-15"), fact("07-15"), "deadline_close", 2026, "confirmed", None),
    (fact("07-15"), fact("07-15"), "deadline_close", 2027, "unconfirmed", "cycle_old:2026"),
    (fact("07-15", cycle=None, quote="apply via uni-assist"), fact("07-15", cycle=None, quote="apply via uni-assist"),
     "deadline_close", 2026, "unconfirmed", "cycle_unknown"),
    (fact("07-15", cycle="2027", quote="apply via uni-assist"), fact("07-15", cycle="2027", quote="apply via uni-assist"),
     "deadline_close", 2026, "unconfirmed", "cycle_unknown"),  # a year not on the page does not count
    (fact("07-15"), fact("07-01"), "deadline_close", 2026, "unconfirmed", "readings_disagree"),
    (fact("07-15"), None, "deadline_close", 2026, "unconfirmed", "single_reading"),
    (fact("07-15"), fact("07-15", quote="by 15 July 2027"), "deadline_close", 2026, "unconfirmed", "B:quote_not_on_page"),
    (fact("uni_assist", url="https://agency.com/p"), fact("uni_assist"), "application_route", 2026, "unconfirmed", "A:url_not_read"),
    (fact("uni_assist"), fact("uni_assist", cycle=None), "application_route", 2027, "confirmed", None),  # procedural: no cycle needed
    (None, None, "deadline_close", 2026, "not_found", None),
])
def test_judge(a, b, field, min_cycle, status, reason):
    v = judge(field, a, b, PAGE_TEXT, ("uni-x.de",), min_cycle)
    assert v.status == status
    if reason:
        assert reason in v.reasons


def test_judge_not_official_even_if_quote_matches():
    pages = {"https://agency.com/p": PAGE_TEXT[UNI + "/p"]}
    v = judge("application_route", fact("uni_assist", url="https://agency.com/p"),
              fact("uni_assist", url="https://agency.com/p"), pages, ("uni-x.de",), 2026)
    assert v.status == "unconfirmed" and "A:not_official" in v.reasons


def test_quote_match_ignores_case_and_whitespace():
    v = judge("application_route", fact("uni_assist", quote="APPLY  via\nuni-assist"), fact("uni_assist"),
              PAGE_TEXT, ("uni-x.de",), 2026)
    assert v.status == "confirmed"


# --- matching and scoring ------------------------------------------------------------------


@pytest.mark.parametrize("field,key,agent,ok", [
    ("semester_contribution_eur", {"value": 340.5, "approx": True}, 320.0, True),
    ("semester_contribution_eur", {"value": 340.5, "approx": True}, 300.0, False),
    ("semester_contribution_eur", {"value": 322.8}, 322.8, True),
    ("english_requirement", {"ielts": 5.5, "toefl_ibt": 72}, English(ielts=5.5, toefl_ibt=72, cefr="B2"), True),
    ("english_requirement", {"ielts": 5.5, "toefl_ibt": 72}, English(ielts=6.0, toefl_ibt=72), False),
    ("english_requirement", {"moi_accepted": False, "ielts": 6.0}, English(ielts=6.0), False),
    ("german_requirement", {"level": "A1", "when": "application"}, German(level="A1", when="with the application"), True),
    ("admission_test", {"any_of": ["TestAS >= 100", "GATE", "GRE Q160"]}, {"any_of": ["GRE", "GATE", "TestAS"]}, True),
    ("admission_test", {"any_of": ["GRE Q >= 157"]}, {"any_of": ["GRE", "GATE"]}, False),
    ("intakes", ["winter", "summer"], ["summer", "winter"], True),
    ("deadline_close", "07-15", "07-15", True),
    ("application_route", "direct", "uni_assist", False),
])
def test_match_key(field, key, agent, ok):
    assert match_key(field, key, agent) is ok


def test_scorable():
    assert not scorable("english_requirement", {"other": ["TOEFL or IELTS"]})
    assert not scorable("grade_requirement", {"note": "180 credits"})
    assert not scorable("deadline_open", None)
    assert scorable("grade_requirement", {"german_max": 2.0})


def test_score_rates_and_review_lists():
    key = {
        "p1": {"key_status": "confirmed", "facts": {"deadline_close": "07-15", "application_route": "direct",
               "deadline_open": None, **{f: None for f in ("language_of_instruction", "tuition_fee_non_eu_eur",
               "semester_contribution_eur", "english_requirement", "german_requirement", "grade_requirement",
               "admission_test", "intakes")}}},
        "p2": {"key_status": "needs_followup", "facts": {"deadline_close": "05-15", **{f: None for f in (
               "application_route", "deadline_open", "language_of_instruction", "tuition_fee_non_eu_eur",
               "semester_contribution_eur", "english_requirement", "german_requirement", "grade_requirement",
               "admission_test", "intakes")}}},
    }
    verdicts = {
        "p1": {"deadline_close": Verdict("confirmed", "07-15"), "application_route": Verdict("confirmed", "uni_assist"),
               "deadline_open": Verdict("confirmed", "04-01")},
        "p2": {"deadline_close": Verdict("confirmed", "05-15")},
    }
    s = score(key, verdicts)
    assert (s.scored, s.confirmed, s.correct) == (2, 2, 1)
    assert s.correct_rate == 0.5 and s.confirmed_rate == 1.0
    assert [w["field"] for w in s.wrong] == ["application_route"]
    assert [e["field"] for e in s.extras] == ["deadline_open"]
    assert [u["ref"] for u in s.unsettled] == ["p2"]
    assert s.verdict() == (False, ["correct_rate 0.500 < 0.95"])


# --- the real programme list ----------------------------------------------------------------


def test_programme_list_has_no_answers_and_official_domains():
    progs = load_programmes()
    assert len(progs) == 30 and len({p.ref for p in progs}) == 30
    assert set(Programme.__dataclass_fields__) == {"ref", "university", "programme", "start_urls", "domains"}
    for p in progs:
        assert p.start_urls and all(is_official(u, p.domains) for u in p.start_urls), p.ref
    assert dict((p.ref, p.domains) for p in progs)["saarland-embedded-systems"] == ("uni-saarland.de",)


# --- end to end on a fake model --------------------------------------------------------------


def canned(info: AgentInfo, values: dict) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, values)])


def test_research_end_to_end(tmp_path):
    prog = Programme("uni-x-data", "Uni X", "Data (MSc)", (UNI + "/msc-data",), ("uni-x.de",))
    f = fetcher(tmp_path, {UNI + "/msc-data": (200, PROGRAMME_HTML), UNI + "/apply/deadlines": (200, DEADLINES_HTML)})
    deadline = {"value": "07-15", "quote": "application period 1 April to 15 July", "url": UNI + "/apply/deadlines",
                "cycle": "Winter semester 2026/27"}
    route = {"value": "uni_assist", "quote": "apply via uni-assist", "url": UNI + "/msc-data", "cycle": None}
    language = {"value": "english", "quote": "The programme is taught in English.", "url": UNI + "/msc-data", "cycle": None}

    def model_fn(messages, info: AgentInfo) -> ModelResponse:
        prompt = str(messages[0])
        assert "=== PAGE " + UNI + "/apply/deadlines" in prompt and "var x" not in prompt
        is_b = "checking a study-abroad plan" in prompt
        # Reading B invents the language quote; reading A misses the opening date.
        values = {"deadline_close": deadline, "application_route": route,
                  "language_of_instruction": {**language, "quote": "Taught entirely in English"} if is_b else language}
        return canned(info, values)

    results = asyncio.run(research([prog], f, FunctionModel(model_fn), min_cycle=2026))
    v = results["uni-x-data"]["verdicts"]
    assert v["deadline_close"].status == "confirmed" and v["deadline_close"].cycle_year == 2026
    assert v["application_route"].status == "confirmed"
    assert v["language_of_instruction"].status == "unconfirmed" and "B:quote_not_on_page" in v["language_of_instruction"].reasons
    assert v["deadline_open"].status == "not_found"

    key = {"uni-x-data": {"key_status": "confirmed", "facts": {
        "deadline_close": "07-15", "application_route": "direct", "language_of_instruction": "english",
        "deadline_open": "04-01", **{k: None for k in ("tuition_fee_non_eu_eur", "semester_contribution_eur",
        "english_requirement", "german_requirement", "grade_requirement", "admission_test", "intakes")}}}}
    rep = report(results, key, 1.0, "fake", 2026)
    assert (rep["scored"], rep["confirmed"], rep["correct"]) == (4, 2, 1)
    assert rep["pass"] is False and rep["fabricated_quotes"] == 1
    assert rep["wrong"][0]["field"] == "application_route" and rep["pages_read"] == 2


def test_answer_key_refs_match_programme_list():
    assert {p.ref for p in load_programmes()} == set(load_key())
