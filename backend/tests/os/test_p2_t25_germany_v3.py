"""P2-T25 (W10 option 3; R-17, R-18, R-21, R-29): the shipped Germany master playbook version 3 asks for the transcript
(`shown`, cited to S2's master's section) and the CGPA (`stated`) on the two application steps. Version 2 is unchanged.
Pure: no database. Fictional students only; the database flow of row 6.21 on version 3 is in test_connect_t8_flow.py."""

import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from app.os.compiler import compile_plan
from app.os.contracts.route_contract import RouteContract
from app.os.knowledge import Fact
from app.os.playbooks import PLAYBOOK_DIR, load_playbook_dir, newest_plain, select_playbook
from app.os.requests.state import QuestionRef, StudentState

pytestmark = [pytest.mark.req("R-17"), pytest.mark.req("R-18"), pytest.mark.req("R-21"), pytest.mark.req("R-29")]

REPO = Path(__file__).resolve().parents[3]
V2_FILE, V3_FILE = PLAYBOOK_DIR / "germany_master.v2.yaml", PLAYBOOK_DIR / "germany_master.v3.yaml"
SPIKE5 = REPO / "docs" / "os" / "spikes" / "spike5-germany-playbook.md"
S2_URL = "https://www.uni-assist.de/en/how-to-apply/plan-your-application/educational-certificates-translations/"
# S2, "For master's applications", accordion "University studies certificates" (check 1: curl, 2026-11-14 22:34 UTC,
# sha256 4ccf4a3166742df0eed95c5f2cf3bfdd70d78a059d2cfca43fad84f528a49bf1; W10 check 2: the same, 2026-11-13)
MASTERS_QUOTE = ("Please upload all certificates in their entirety. Include the diploma certificate as well as the "
                 "overview of all subjects and grades (transcript).")
BACHELORS_ONLY = "Please upload a complete overview of all subjects and grades (transcript), issued by your university."
GPA, TRANSCRIPT = "education.bachelor.gpa", "transcript"
APPLY = ("uni_assist_apply", "direct_apply")
TODAY = date(2027, 3, 1)


def books():
    return load_playbook_dir(PLAYBOOK_DIR)


def germany(refs=("tu-x", "uni-y")) -> RouteContract:
    return RouteContract.model_validate({
        "contract_version": "1", "source": "self_serve", "external_ref": "g", "student_ref": "stu-1",
        "origin_country": "PK", "destination_country": "DE", "level": "master",
        "target_intake": {"term": "winter", "year": 2027},
        "programmes": [{"programme_ref": r, "rank": i + 1} for i, r in enumerate(refs)]})


def programme_facts(refs=("tu-x", "uni-y")) -> dict:
    """Fictional Knowledge rows: `uni_assist_vpd` (both application steps, for every programme) and a deadline."""
    checked = datetime(2026, 10, 17, tzinfo=timezone.utc)

    def fact(value) -> Fact:
        return Fact(value, "q", "https://uni.example/x", checked, 2027, "confirmed")

    return {**{(r, "application_route"): fact("uni_assist_vpd") for r in refs},
            **{(r, "deadline_close"): fact({"date": "2027-07-15"}) for r in refs}}


def flat(text: str) -> str:
    """Comment marks and line breaks removed, so a quote wrapped over lines reads as one."""
    return re.sub(r"\s+", " ", re.sub(r"^\s*#\s?", "", text, flags=re.M))


# --- v3 loads and validates ------------------------------------------------------------------------------------------


def test_v3_loads_validates_and_is_v2_plus_the_two_needs():
    loaded = books()
    v2, v3 = loaded[("germany_master", 2)], loaded[("germany_master", 3)]
    assert v3.declares_needs and v3.require_citations
    for key in APPLY:
        step = next(t for t in v3.tasks if t.template_key == key)
        assert [(n.kind, n.ref, n.evidence) for n in step.needs] == [
            ("document", "ssc_certificate", "shown"), ("document", "hssc_certificate", "shown"),
            ("document", TRANSCRIPT, "shown"), ("fact", GPA, "stated")]
    assert sorted(set(v3.asks) - set(v2.asks)) == sorted([TRANSCRIPT, GPA])
    # everything else is version 2's: the same route, steps, constants, eligibility, pages and sources (S2 re-dated)
    a, b = v2.model_dump(mode="json", by_alias=True), v3.model_dump(mode="json", by_alias=True)
    for t in b["tasks"]:
        t["needs"] = [n for n in t["needs"] if n.get("document") != TRANSCRIPT and n.get("fact") != GPA]
    for k in (TRANSCRIPT, GPA):
        b["asks"].pop(k)
    assert b["sources"].pop("S2") == {"checked": "2026-11-14", "confirmed": True}
    a["sources"].pop("S2")
    assert {**a, "version": 3} == b


def test_a_new_plan_with_the_needs_gate_on_gets_v3_and_the_gate_off_still_gets_v1():
    loaded = books()
    assert select_playbook(loaded, "PK", "DE", "master", with_needs=True).version == 3
    assert select_playbook(loaded, "PK", "DE", "master").version == 1
    assert newest_plain(loaded.values())["germany_master"].version == 1


# --- the transcript need cites S2's master's section with the exact quote ---------------------------------------------


def test_the_transcript_need_cites_s2_with_the_masters_quote():
    v3 = books()[("germany_master", 3)]
    ask = v3.asks[TRANSCRIPT]
    assert ask.shown == "Upload your final transcript"
    assert [(c.source, str(c.url)) for c in ask.citations] == [("S2", S2_URL)]
    text = V3_FILE.read_text(encoding="utf-8")
    above = text.split("\n  transcript:\n")[0].rsplit("hssc_certificate:", 1)[1]  # the comment just above the ask
    assert f'"{MASTERS_QUOTE}"' in flat(above)
    assert "For master's applications" in flat(above) and "University studies certificates" in flat(above)
    assert "4ccf4a3166742df0eed95c5f2cf3bfdd70d78a059d2cfca43fad84f528a49bf1" in above
    assert BACHELORS_ONLY not in flat(text)  # the bachelor's section's sentence is not cited for master's
    # the walkthrough holds the same quote, as S2 (whose URL is the citation's), confirmed
    spike = flat(SPIKE5.read_text(encoding="utf-8"))
    a11 = spike.split("**A11. ")[1].split("### Phase B")[0]
    assert f'"{MASTERS_QUOTE}" **confirmed**' in a11 and "For master's applications" in a11
    assert f"- S2. uni-assist, Educational certificates & translations. {S2_URL}" in spike


def test_the_cgpa_is_a_stated_fact_with_no_rule_of_its_own():
    v2, v3 = books()[("germany_master", 2)], books()[("germany_master", 3)]
    ask = v3.asks[GPA]
    assert (ask.stated, ask.which_is_right) == ("Tell us your final CGPA", "Which CGPA is right?")
    assert (ask.shown, ask.confirmed, ask.expected) == (None, None, None)
    assert [(c.source, str(c.url)) for c in ask.citations] == [("S2", S2_URL)]
    assert v3.eligibility == v2.eligibility and v3.constants == v2.constants  # no CGPA minimum or figure added
    assert v3.eligibility.grade_scales["cgpa_4"].value == "transcript.cgpa"  # the grade estimate's own reading


# --- a CGPA stated and a CGPA on the transcript: a "which is right" step ----------------------------------------------


def test_a_missing_cgpa_and_transcript_are_asked_and_block_both_application_steps():
    v3 = books()[("germany_master", 3)]
    d = compile_plan(germany(), v3, {}, programme_facts(), TODAY, student=StudentState())
    keys = {t.instance_key for t in d.tasks}
    assert {f"provide@fact:{GPA}:stated", f"provide@document:{TRANSCRIPT}:shown"} <= keys
    titles = {t.instance_key: t.title for t in d.tasks}
    assert titles[f"provide@fact:{GPA}:stated"] == "Tell us your final CGPA"
    assert titles[f"provide@document:{TRANSCRIPT}:shown"] == "Upload your final transcript"
    for t in d.tasks:
        if t.template_key in APPLY:
            assert (f"provide@fact:{GPA}:stated", True) in t.depends_on
            assert (f"provide@document:{TRANSCRIPT}:shown", True) in t.depends_on


@pytest.mark.req("R-21")
def test_a_stated_cgpa_against_the_transcripts_cgpa_gives_a_which_is_right_step():
    v3 = books()[("germany_master", 3)]
    docs = {"ssc_certificate": "confirmed", "hssc_certificate": "confirmed", TRANSCRIPT: "confirmed"}
    # the Vault's card: 3.4 said in chat, 3.2 on the confirmed transcript (the conflict reaches the OS as a question)
    state = StudentState(facts={GPA: "stated"}, documents=docs,
                         questions={f"fact:{GPA}": QuestionRef("vault", "profile_issue:1")})
    d = compile_plan(germany(), v3, {}, programme_facts(), TODAY, student=state)
    ask = next(t for t in d.tasks if t.instance_key == f"which_is_right@fact:{GPA}:stated")
    assert (ask.task_type, ask.inbox_kind, ask.title) == ("student.choose", "choose", "Which CGPA is right?")
    assert list(ask.citations) == [{"source": "S2", "url": S2_URL}]
    applying = [t for t in d.tasks if t.template_key in APPLY]
    assert len(applying) == 4  # two programmes, both routes
    for t in applying:
        assert t.blocked_reason == f"which_is_right:{GPA}" and (ask.instance_key, True) in t.depends_on
    assert not [t for t in d.tasks if t.instance_key.startswith(f"provide@fact:{GPA}")]
    # answered: the question goes and the steps are free of it
    done = compile_plan(germany(), v3, {}, programme_facts(), TODAY,
                        student=StudentState(facts={GPA: "stated"}, documents=docs))
    assert f"which_is_right@fact:{GPA}:stated" in done.answered
    assert not [t for t in done.tasks if (t.blocked_reason or "").startswith("which_is_right:")]


# --- v2 plans are unchanged ------------------------------------------------------------------------------------------


def test_v2_is_unchanged_and_a_v2_draft_is_the_same_with_v3_loaded():
    loaded = books()
    v2 = loaded[("germany_master", 2)]
    text = V2_FILE.read_text(encoding="utf-8")
    assert "transcript:" not in text and GPA not in text and "version: 2\n" in text
    state = StudentState(facts={GPA: "stated"}, questions={f"fact:{GPA}": QuestionRef("vault", "profile_issue:1")})
    d = compile_plan(germany(), v2, {}, programme_facts(), TODAY, student=state)
    assert d.playbook_version == 2
    assert not [t for t in d.tasks if GPA in t.instance_key or TRANSCRIPT in t.instance_key]  # nothing of v3 on v2
    assert ("germany_master", 3) in loaded  # and v3 is there beside it
