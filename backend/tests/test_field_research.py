"""Shared field notes (BETA_CONVERSATION_SPEC 3.1): built from mocked search,
pages and model only; every fact carries a verbatim quote from its page;
cached per field and country and refreshed by age; skipped while the monthly
cap pauses research; the analyzer and path explain read the note."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.config import config
from app.inference import usage
from app.models import BackgroundJob, PaiFieldNote, PaiPossibility
from app.pai_c.paths import field_research
from app.pai_c.paths.field_research import (JOB_FIELD_RESEARCH, enqueue_missing, field_research_job, fresh_note,
                                            prompt_notes)
from app.pai_c.possibilities import PossibilityService
from scripts.counselor_eval_support import StudentSession
from tests.test_path_analyzer import VAULT_ITEM, add_education, analysis, path, seed, title
from tests.test_path_engine_vault import run_job

FIELD = "electrical_engineering"
PAGE_A = "https://www.hec.gov.pk/careers/electrical"
PAGE_B = "https://www.pec.org.pk/electrical-demand"
TEXT_A = ("Electrical engineers study circuits, power systems and electronics. "
          "A typical day includes design reviews and testing equipment on site. "
          "Graduates of University of the Punjab often join power companies.")
TEXT_B = "Demand for electrical engineers is rising with new solar projects across the country."
SEARCH = "app.pai_c.paths.field_research.search_web"
READ = "app.pai_c.paths.field_research.read_page"
MODEL = "app.pai_c.paths.field_research.complete"


def model_reply():
    return {"sections": {
        "what_you_study": [{"text": "You study circuits, power and electronics.",
                            "quote": "Electrical engineers study circuits, power systems and electronics.",
                            "source_url": PAGE_A}],
        "work_day": [{"text": "Days mix design reviews and testing on site.",
                      "quote": "A typical day includes design reviews and testing equipment on site.",
                      "source_url": PAGE_A},
                     {"text": "Engineers work night shifts.", "quote": "Engineers mostly work night shifts.",
                      "source_url": PAGE_A}],  # not on the page: dropped
        "entry": [{"text": "Graduates of University of the Punjab join power companies.",
                               "quote": "Graduates of University of the Punjab often join power companies.",
                               "source_url": PAGE_A}],  # names an institution: dropped
        "jobs_and_demand": [{"text": "Demand for electrical engineers is rising with solar projects.",
                             "quote": "Demand for electrical engineers is rising with new solar projects across the country.",
                             "source_url": PAGE_B},
                            {"text": "Demand is high.", "quote": "Demand for electrical engineers is rising",
                             "source_url": "https://unread.example.com/x"}],  # a page never read: dropped
        "myths": "not a list"}}


async def run_research(db, *, reply=None, payload=None):
    """One field research job with fake search, pages and model."""
    pages = {PAGE_A: {"url": PAGE_A, "text": TEXT_A}, PAGE_B: {"url": PAGE_B, "text": TEXT_B}}
    search = AsyncMock(return_value=[{"url": PAGE_A}, {"url": "http://insecure.example.com"}, {"url": PAGE_B}])
    read = AsyncMock(side_effect=lambda url, chars: pages.get(url))
    model = AsyncMock(return_value=json.dumps(reply or model_reply()))
    job = SimpleNamespace(id="job-field", workspace_id=None,
                          payload=payload or {"field_key": FIELD, "country": "pakistan"})
    with patch(SEARCH, search), patch(READ, read), patch(MODEL, model):
        result = await field_research_job(job, db)
    return result, search, read, model


STUDY_QUOTE = "Electrical engineers study circuits, power systems and electronics."
DEMAND_QUOTE = "Demand for electrical engineers is rising with new solar projects across the country."
PAY_QUOTE = "Electrical engineers are paid very well in almost every company we surveyed."
BLOG = "https://careers-blog.example.com/pay"


def store_note(db, field_key=FIELD, *, age_days=0, country="pakistan"):
    db.add(PaiFieldNote(field_key=field_key, country=country, confidence="medium",
                        researched_at=datetime.now(timezone.utc) - timedelta(days=age_days),
                        note={"sections": {"what_you_study": [{"text": f"You study the core of {field_key}.",
                                                               "quote": STUDY_QUOTE, "source_url": PAGE_A,
                                                               "confidence": "trusted"}],
                                           "jobs_and_demand": [{"text": "Demand is rising.",
                                                                "quote": DEMAND_QUOTE, "source_url": PAGE_B,
                                                                "confidence": "trusted"},
                                                               {"text": "Pay is very high.", "quote": PAY_QUOTE,
                                                                "source_url": BLOG, "confidence": "uncertain"}]}},
                        sources=[{"url": PAGE_A}, {"url": PAGE_B}]))
    db.commit()


# ---- the note ------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_note_built_from_sources_with_verified_quotes():
    with StudentSession() as student, student.factory() as db:
        result, search, read, model = await run_research(db)
        row = db.scalar(select(PaiFieldNote))
    assert result["status"] == "stored" and result["facts"] == 3
    assert (row.field_key, row.country) == (FIELD, "pakistan")
    sections = row.note["sections"]
    assert set(sections) == {"what_you_study", "work_day", "jobs_and_demand"}
    for facts in sections.values():
        for fact in facts:
            page = TEXT_A if fact["source_url"] == PAGE_A else TEXT_B
            assert fact["quote"] in page and set(fact) == {"text", "source_url", "quote", "confidence"}
            assert fact["confidence"] == "trusted"  # hec.gov.pk and pec.org.pk are trusted
    assert "University" not in json.dumps(sections)
    assert [source["url"] for source in row.sources] == [PAGE_A, PAGE_B]
    assert row.confidence == "medium"
    # Two queries from the field title and the country; only https pages are read.
    queries = [call.args[0] for call in search.await_args_list]
    assert len(queries) == 2 and all(title(FIELD) in q and "Pakistan" in q for q in queries)
    assert [call.args[0] for call in read.await_args_list] == [PAGE_A, PAGE_B]
    # One `researcher` call in JSON mode, the pages as data.
    assert model.await_count == 1 and model.await_args.kwargs["role"] == "researcher"
    assert model.await_args.kwargs["response_format"] == {"type": "json_object"}
    assert TEXT_B in model.await_args.kwargs["messages"][0]["content"]


@pytest.mark.asyncio
async def test_no_pages_or_no_verified_fact_stores_nothing():
    with StudentSession() as student, student.factory() as db:
        with patch(SEARCH, AsyncMock(return_value=[])), patch(MODEL, AsyncMock()) as model:
            result = await field_research_job(SimpleNamespace(payload={"field_key": FIELD, "country": "pakistan"}), db)
        assert result["status"] == "no_sources" and model.await_count == 0
        result, *_ = await run_research(db, reply={"sections": {"work_day": [
            {"text": "Made up.", "quote": "Not on any page.", "source_url": PAGE_A}]}})
        assert result["status"] == "no_verified_facts"
        assert db.scalar(select(PaiFieldNote)) is None


@pytest.mark.asyncio
async def test_cached_then_refreshed_by_age():
    with StudentSession() as student, student.factory() as db:
        await run_research(db)
        again, search, _, model = await run_research(db)
        assert again["status"] == "fresh" and search.await_count == 0 and model.await_count == 0
        assert enqueue_missing(db, [FIELD], "Pakistan") == []
        row = db.scalar(select(PaiFieldNote))
        row.researched_at = datetime.now(timezone.utc) - timedelta(days=config.PAI_FIELD_NOTE_DAYS + 1)
        row.note = {"sections": {}}
        db.commit()
        assert fresh_note(db, FIELD, "Pakistan") is None
        assert len(enqueue_missing(db, [FIELD], "Pakistan")) == 1
        refreshed, *_ = await run_research(db)
        db.expire_all()
        row = db.scalar(select(PaiFieldNote))
        assert refreshed["status"] == "stored" and row.note["sections"]
        assert fresh_note(db, FIELD, " pakistan ") is not None
        assert len(db.scalars(select(PaiFieldNote)).all()) == 1


def test_enqueue_is_idempotent_and_capped():
    fields = ["electrical_engineering", "electronic_engineering", "computer_engineering",
              "mechanical_engineering", "civil_engineering", "chemical_engineering", "biomedical_engineering"]
    with StudentSession() as student, student.factory() as db:
        store_note(db, "electronic_engineering")
        queued = enqueue_missing(db, [*fields, "not_a_field"], "Pakistan")
        db.commit()
        assert len(queued) == 5
        jobs = db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_FIELD_RESEARCH)).all()
        keys = [job.payload["field_key"] for job in jobs]
        assert "electronic_engineering" not in keys and keys[0] == "electrical_engineering"
        assert all(job.workspace_id is None and job.payload["country"] == "pakistan" for job in jobs)
        # Pending jobs are not queued again; the rest of the list fills the next run.
        assert enqueue_missing(db, fields, "Pakistan") == [
            job.id for job in db.scalars(select(BackgroundJob).where(
                BackgroundJob.job_type == JOB_FIELD_RESEARCH,
                BackgroundJob.payload["field_key"].as_string() == "biomedical_engineering")).all()]


@pytest.mark.asyncio
async def test_research_paused_means_no_run():
    paused = {"month": "", "spent": 85.0, "cap": 100.0, "stage": "research_paused"}
    with StudentSession() as student, student.factory() as db, \
            patch.object(usage, "cap_state", lambda: paused), patch.object(usage, "_gate_logged", {}):
        result, search, read, model = await run_research(db)
        assert result == {"status": "cap_paused"}
        assert search.await_count == read.await_count == model.await_count == 0
        assert db.scalar(select(PaiFieldNote)) is None


def test_prompt_notes_give_ids_and_skip_stale_notes():
    with StudentSession() as student, student.factory() as db:
        store_note(db, FIELD)
        store_note(db, "civil_engineering", age_days=config.PAI_FIELD_NOTE_DAYS + 5)
        block, facts = prompt_notes(db, [FIELD, "civil_engineering"], "Pakistan")
    assert [entry["field_key"] for entry in block] == [FIELD]
    assert [fact["id"] for fact in block[0]["facts"]] == [f"note:{FIELD}:1", f"note:{FIELD}:2"]
    assert facts[f"note:{FIELD}:2"]["source_url"] == PAGE_B
    assert "quote" not in block[0]["facts"][0]


# ---- the analyzer reads and queues notes -------------------------------------------------

def research_jobs(db):
    return db.scalars(select(BackgroundJob).where(BackgroundJob.job_type == JOB_FIELD_RESEARCH)).all()


@pytest.mark.asyncio
async def test_analyzer_cites_note_facts_with_sources():
    cited = path(FIELD)
    cited["note_ids"] = [f"note:{FIELD}:2", "note:civil_engineering:1", f"note:{FIELD}:99"]
    with StudentSession() as student, student.factory() as db:
        seed(student, db)
        add_education(student, db)
        store_note(db, FIELD)
        store_note(db, "civil_engineering")
        result, prompt, _ = await run_job(student, db, analysis(cited))
        row = db.scalar(select(PaiPossibility).where(PaiPossibility.title == title(FIELD)))
        queued = [job.payload["field_key"] for job in research_jobs(db)]
    block = json.loads(prompt.split("<field_notes>")[1].split("</field_notes>")[0])
    assert {entry["field_key"] for entry in block} == {FIELD, "civil_engineering"}
    assert result["status"] == "stored"
    world = [item for item in row.evidence if item.get("source_url")]
    # Only a fact of the path's own field that was shown is kept, with its source.
    assert world == [{"text": "Demand is rising.", "item_id": f"note:{FIELD}:2", "evidence_level": "source",
                      "source_label": None, "source_url": PAGE_B}]
    assert any(item["item_id"] == VAULT_ITEM for item in row.evidence)
    # After the run: candidate fields without a fresh note, at most field_notes_per_run.
    assert 0 < len(queued) <= field_research.policy()["field_notes_per_run"]
    assert FIELD not in queued and "civil_engineering" not in queued


@pytest.mark.asyncio
@pytest.mark.parametrize("researcher_paused", [False, True])
async def test_analyzer_without_field_notes(researcher_paused):
    allowed = usage.role_allowed
    with StudentSession() as student, student.factory() as db, \
            patch.object(usage, "role_allowed", lambda role: not (researcher_paused and role == "researcher")
                         and allowed(role)):
        seed(student, db)
        add_education(student, db)
        result, prompt, _ = await run_job(student, db, analysis(path(FIELD)))
        rows = PossibilityService(db).list(student.workspace_id)
        queued = research_jobs(db)
    assert "<field_notes>" not in prompt
    assert result["status"] == "stored" and result["paths"] == [rows[0].id]
    assert all(set(item) == {"text", "item_id", "evidence_level", "source_label"} for item in rows[0].evidence)
    assert (queued == []) if researcher_paused else (0 < len(queued) <= 5)


@pytest.mark.asyncio
async def test_a_failing_note_enqueue_never_fails_the_run():
    with StudentSession() as student, student.factory() as db, \
            patch("app.pai_c.paths.field_research.enqueue_missing", side_effect=RuntimeError("down")):
        seed(student, db)
        add_education(student, db)
        result, _, _ = await run_job(student, db, analysis(path(FIELD)))
    assert result["status"] == "stored"


# ---- path explain reuses the note --------------------------------------------------------

@pytest.mark.asyncio
async def test_path_explain_reuses_the_note_as_its_first_source():
    from app.pai_c.paths import explain as explain_module
    from tests.test_path_explanation import explanation
    with StudentSession() as student, student.factory() as db:
        store_note(db, FIELD)
        invoke = AsyncMock(return_value={"ok": True, "data": {"results": []}})
        context = SimpleNamespace(workspace_id=None, tools=SimpleNamespace(invoke=invoke))
        brief = {"possibility_id": "p", "relevance_version": "v", "title": title(FIELD), "why": "",
                 "evidence": [{"text": "I enjoy making things"},
                              {"text": "Demand is rising.", "source_url": PAGE_B}],
                 "field_key": FIELD, "country": "Pakistan"}
        reply = {**explanation(), "world_facts": [
            {"field": "jobs", "value": "Demand is rising", "quote": DEMAND_QUOTE, "source_url": PAGE_B}]}
        with patch.object(explain_module, "complete", AsyncMock(return_value=json.dumps(reply))) as model:
            result = await explain_module.explain(context, {"brief": brief})
    sent = json.loads(model.await_args.kwargs["messages"][0]["content"])
    assert [page["url"] for page in sent["pages"]][:3] == [PAGE_A, PAGE_B, BLOG]
    # The note covers fetch_limit pages: no search and no fetch.
    assert invoke.await_count == 0
    assert DEMAND_QUOTE in [fact["quote"] for fact in [*result["facts"], *result["unconfirmed"]]]
    # A note fact on the path is never accepted as the student's evidence.
    bad = {**explanation(), "fit_for": [{"observation": "x", "evidence": "Demand is rising."}]}
    with pytest.raises(ValueError):
        explain_module.validate_explanation(json.dumps(bad), brief)


def test_research_prompts_are_synced_into_the_prompt_document():
    from pathlib import Path
    from app.pai_c.deep.prompts import load_prompt
    doc = (Path(__file__).parents[2] / "docs/counselor/COUNSELOR_V3_PROMPTS.md").read_text(encoding="utf-8")
    for name in ("field_research", "rules_refresh", "path_analyzer"):
        assert load_prompt(name).strip() in doc


# ---- fix round 1: real quotes, institutions, trusted sources ----------------------------

from app.pai_c.paths.field_research import institution_blocklist, names_institution, verified_facts  # noqa: E402

PAY_PAGE = ("Electrical engineers earn high salaries. They study circuits. "
            "Most electrical engineers start in design or maintenance roles at power and telecom companies.")
LONG_QUOTE = "Most electrical engineers start in design or maintenance roles at power and telecom companies."


def check(text, quote, url=PAGE_A, page=PAY_PAGE):
    rules = field_research.policy()
    kept = verified_facts({"sections": {"work_day": [{"text": text, "quote": quote, "source_url": url}]}},
                          [{"url": url, "text": page}], rules, datetime.now(timezone.utc),
                          blocked=institution_blocklist(None), trusted=field_research.trusted_domains())
    return kept.get("work_day", [])


def test_a_short_or_unsupported_quote_never_verifies_a_fact():
    assert check("Every graduate earns PKR 500,000 a month guaranteed.", "a") == []
    assert check("Every graduate earns PKR 500,000 a month guaranteed.",
                 "Electrical engineers earn high salaries.") == []  # too short
    # A number in the fact that the quote does not state drops it.
    assert check("Most graduates start in 3 design roles at power companies.", LONG_QUOTE) == []
    # Words that do not overlap the quote drop it.
    assert check("Doctors treat patients in hospitals every single day.", LONG_QUOTE) == []
    kept = check("Most graduates start in design or maintenance roles at power companies.", LONG_QUOTE)
    assert len(kept) == 1 and kept[0]["confidence"] == "trusted"


def test_whitespace_in_a_page_does_not_break_a_real_quote():
    page = LONG_QUOTE.replace("design or ", "design or\n")
    assert check("Most graduates start in design or maintenance roles at power companies.", LONG_QUOTE, page=page)


@pytest.mark.parametrize("sentence", [
    "Students of FAST often work abroad after the degree is complete.",
    "UMT graduates usually find design work after the degree.",
    "Graduates of the university of lahore often join power companies.",
    "GCU Lahore runs a strong programme in this field for students.",
    "UCP students often join software houses after the degree.",
    "Riphah offers the degree with clinical rotations for students.",
    "Many Central Punjab Institute students join power companies.",
    "The Indus Valley School of Art trains designers well.",
])
def test_institution_names_are_blocked(sentence):
    from app.models import Institution, InstitutionDomain
    with StudentSession() as student, student.factory() as db:
        for name, domain in (("Central Punjab Institute", "cpi.edu.pk"), ("Indus Valley School", "riphah.edu.pk")):
            institution = Institution(name=name, normalized_name=name.lower(), country_code="PK", source="catalog")
            db.add(institution)
            db.flush()
            db.add(InstitutionDomain(institution_id=institution.id, domain=domain, source_url=f"https://{domain}",
                                     origin="catalog", checked_at=datetime.now(timezone.utc)))
        db.commit()
        blocked = institution_blocklist(db)
    assert names_institution(sentence, blocked, field_research.policy())


def test_generic_words_are_not_institutions():
    blocked = institution_blocklist(None)
    for sentence in ("Most universities ask for FSc Pre-Engineering with good marks.",
                     "The degree takes four years at a university.",
                     "Engineers work fast when a deadline is close."):
        assert not names_institution(sentence, blocked, field_research.policy()), sentence


def test_an_untrusted_source_is_kept_uncertain_and_never_cited():
    kept = check("Most graduates start in design or maintenance roles at power companies.", LONG_QUOTE,
                 url="https://careers-blog.example.com/x")
    assert kept and kept[0]["confidence"] == "uncertain"
    with StudentSession() as student, student.factory() as db:
        store_note(db, FIELD)
        block, facts = prompt_notes(db, [FIELD], "Pakistan")
    assert facts and all(fact["source_url"] != BLOG for fact in facts.values())
    assert "Pay is very high." not in json.dumps(block)
    # Regulators named in admission_rules.json (official rows) and the research policy are trusted.
    assert {"pec.org.pk", "pmdc.pk", "hec.gov.pk"} <= field_research.trusted_domains()


def test_note_confidence_counts_only_trusted_facts():
    rules = field_research.policy()
    facts = {"work_day": [{"text": "t", "quote": "q", "source_url": BLOG, "confidence": "uncertain"}] * 9}
    assert field_research._confidence(facts, rules) == "uncertain"


# ---- fix round 2: the quote must support the claim; negations --------------------------------

def test_an_on_topic_fabrication_is_dropped():
    assert check("Electrical engineers are guaranteed jobs at power companies abroad.", LONG_QUOTE) == []
    assert check("Every graduate is guaranteed a government job abroad after graduation.", LONG_QUOTE) == []


def test_a_true_clause_of_a_long_quote_passes():
    quote = ("Most electrical engineers start in design or maintenance roles at power and telecom companies, "
             "while others move into teaching, research, sales or project management after several years of work.")
    assert check("Most electrical engineers start in design or maintenance roles.", quote, page=quote)


@pytest.mark.parametrize("fact,page", [
    ("Electrical engineering programs require 60% marks in FSc for admission.",
     "Electrical engineering programs do not require 60% marks in FSc for admission to the degree."),
    ("Electrical engineers work night shifts in testing labs.",
     "Electrical engineers rarely work night shifts; most work in offices and testing labs."),
    ("Most electrical engineers start in design or maintenance roles at power and telecom companies.",
     "Most electrical engineers never start in design or maintenance roles at power and telecom companies."),
])
def test_a_negation_in_only_one_of_fact_and_quote_drops_the_fact(fact, page):
    assert check(fact, page, page=page) == []


def test_the_same_negation_on_both_sides_passes():
    page = "Electrical engineers rarely work night shifts; most work in offices and testing labs."
    assert check("Electrical engineers rarely work night shifts.", page, page=page)


def test_negation_words_are_data_and_not_stopwords():
    rules = field_research.policy()["quote_rules"]
    assert {"not", "no", "never", "rarely", "nahi"} <= set(rules["negations"])
    assert not set(rules["negations"]) & set(rules["stopwords"])
    assert rules["min_support"] == 0.75


@pytest.mark.parametrize("sentence,blocked", [
    ("Many students at Nust study this field.", True),
    ("Lums graduates often join consulting firms.", True),
    ("FAST graduates often work abroad.", True),
    ("Engineers work fast when a deadline is close.", False),
])
def test_known_short_names_match_in_any_case_but_english_words_only_in_capitals(sentence, blocked):
    assert names_institution(sentence, institution_blocklist(None), field_research.policy()) is blocked
