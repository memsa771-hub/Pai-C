"""Programme registry (Slice 2 spec §4.1), the fact source column and insert-only seeding (handoff M6)."""
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from sqlalchemy import func, select

from app.os import models
from app.os.knowledge import Fact, SqlKnowledge, load_seed
from app.os.knowledge.programmes import (
    PROGRAMME_SEED,
    Programme,
    ProgrammeSeedError,
    ProgrammeStore,
    load_programme_seed,
)
from app.os.knowledge.seed import SEED_DIR

KEY = Path(__file__).parent / "quality" / "spike1_answer_key.yaml"
FACT_SEED = SEED_DIR / "germany_ws2027.yaml"
NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)


def test_seed_loads_30_and_is_idempotent(engine, clean):
    store = ProgrammeStore(engine, "pai")
    assert load_programme_seed(PROGRAMME_SEED, store) == 30
    with engine.connect() as conn:
        before = conn.execute(select(models.programmes).order_by(models.programmes.c.ref)).all()
    assert load_programme_seed(PROGRAMME_SEED, store) == 30
    with engine.connect() as conn:
        after = conn.execute(select(models.programmes).order_by(models.programmes.c.ref)).all()
    assert len(after) == 30
    assert [(r.ref, r.name, r.start_urls, r.status) for r in before] == [(r.ref, r.name, r.start_urls, r.status) for r in after]


def test_seed_refs_match_the_answer_key():
    seed = yaml.safe_load(PROGRAMME_SEED.read_text(encoding="utf-8"))["programmes"]
    key = yaml.safe_load(KEY.read_text(encoding="utf-8"))["programmes"]
    assert set(seed) == set(key)


def test_active_lists_29_and_hof_is_excluded(engine, clean):
    store = ProgrammeStore(engine, "pai")
    load_programme_seed(PROGRAMME_SEED, store)
    active = store.active("germany_master")
    assert len(active) == 29
    assert store.get("hof-software-engineering-industrial-applications").status == "excluded"
    p = store.get("ovgu-eeit")
    assert p.official_domains == ("ovgu.de",) and p.start_urls[0].startswith("https://")


def test_seed_does_not_touch_facts(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    load_seed(FACT_SEED, kb)
    with engine.connect() as conn:
        before = conn.execute(select(func.count()).select_from(models.knowledge_facts)).scalar_one()
    load_programme_seed(PROGRAMME_SEED, ProgrammeStore(engine, "pai"))
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(models.knowledge_facts)).scalar_one() == before


def test_upsert_updates_and_tenants_are_separate(engine, clean):
    store = ProgrammeStore(engine, "pai")
    p = Programme(ref="p1", route_key="r", university="U", name="N", aliases=("N",),
                  start_urls=("https://u.example.org/p",), official_domains=("example.org",))
    store.upsert(p)
    store.upsert(replace(p, name="New name"))
    assert store.get("p1").name == "New name"
    assert ProgrammeStore(engine, "other").get("p1") is None


@pytest.mark.parametrize("mutate,msg", [
    (lambda p: p.update(start_urls=["http://insecure.example.org/"]), "https"),
    (lambda p: p.update(official_domains=["https://example.org"]), "bare domain"),
    (lambda p: p.update(status="maybe"), "status"),
    (lambda p: p.pop("name"), "name"),
])
def test_invalid_seed_rejected(tmp_path, mutate, msg):
    data = yaml.safe_load(PROGRAMME_SEED.read_text(encoding="utf-8"))
    mutate(data["programmes"]["ovgu-eeit"])
    path = tmp_path / "programmes.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ProgrammeSeedError, match=msg):
        load_programme_seed(path, store=None)  # validation happens before anything is written


# --- the fact source column and insert-only seeding ------------------------------------------


def _source(engine, ref: str, field: str) -> str:
    with engine.connect() as conn:
        return conn.execute(select(models.knowledge_facts.c.source).where(
            models.knowledge_facts.c.ref == ref, models.knowledge_facts.c.field == field)).scalar_one()


def test_seeded_facts_are_marked_seed(engine, clean):
    load_seed(FACT_SEED, SqlKnowledge(engine, "pai"))
    assert _source(engine, "ovgu-eeit", "deadline_close") == "seed"


def test_reseeding_never_overwrites_a_changed_fact(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    load_seed(FACT_SEED, kb)
    fact_id = kb.programme_facts(["ovgu-eeit"], ["deadline_close"], 2027)[("ovgu-eeit", "deadline_close")].id
    kb.confirm(fact_id, value={"date": "2027-07-15", "tz": "Europe/Berlin"}, quote="until 15 July",
               url="https://www.ovgu.de/x", status="confirmed")
    load_seed(FACT_SEED, kb)  # insert-only: the confirmed fact stays
    fact = kb.programme_facts(["ovgu-eeit"], ["deadline_close"], 2027)[("ovgu-eeit", "deadline_close")]
    assert fact.status == "confirmed" and fact.quote == "until 15 July"
    assert _source(engine, "ovgu-eeit", "deadline_close") == "manual"


def test_admin_supplied_fact_is_marked_manual(engine, clean):
    kb = SqlKnowledge(engine, "pai")
    kb.upsert("programme", "p1", "deadline_close",
              Fact({"date": "2027-07-15"}, "until 15 July", "https://u.example.org", NOW, 2027, "confirmed"))
    assert _source(engine, "p1", "deadline_close") == "manual"


def test_source_check_rejects_unknown_source(engine, clean):
    from sqlalchemy.exc import IntegrityError
    kb = SqlKnowledge(engine, "pai")
    with pytest.raises((IntegrityError, ValueError)):
        kb.upsert("programme", "p1", "deadline_close",
                  Fact({"date": "2027-07-15"}, "q", "https://u.example.org", NOW, 2027, "unconfirmed"),
                  source="rumour")
