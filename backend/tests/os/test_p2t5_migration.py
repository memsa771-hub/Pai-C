"""P2-T5: migration os_0028 (reviewers, review items, checks, evidence, attestations) and the review policy file.
Fictional data."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from sqlalchemy import create_engine, inspect, insert
from sqlalchemy.exc import IntegrityError

from app.os import models
from app.os.db import OS_SCHEMA
from app.os.knowledge.review.policy import POLICY_FILE, load_policy, parse
from tests.os.conftest import run_alembic

pytestmark = pytest.mark.req("R-42")
NEW = {"os_reviewers", "os_review_items", "os_review_files", "os_fact_reviews", "os_review_attestations"}


def test_os_0028_upgrade_downgrade(os_db, engine, clean):
    assert NEW <= set(inspect(engine).get_table_names(schema=OS_SCHEMA))
    engine.dispose()
    run_alembic(["downgrade", "os_0027"], os_db)
    try:
        eng = create_engine(os_db)
        try:
            assert not NEW & set(inspect(eng).get_table_names(schema=OS_SCHEMA))
        finally:
            eng.dispose()
    finally:
        run_alembic(["upgrade", "os@head"], os_db)


def test_downgrade_refuses_to_drop_records(os_db, engine, clean):
    with engine.begin() as conn:
        conn.execute(insert(models.reviewers).values(tenant_id="pai", ref="amina", display_name="A", identity="amina",
                                                     role="checker", token_hash="h1"))
    engine.dispose()
    with pytest.raises(Exception):
        run_alembic(["downgrade", "os_0027"], os_db)


def _reviewer(conn, ref="amina", token="h1", **kw) -> int:
    return conn.execute(insert(models.reviewers).values(
        tenant_id="pai", ref=ref, display_name=ref, identity=ref, role="checker", token_hash=token, **kw
    ).returning(models.reviewers.c.id)).scalar()


def _item(conn, key="k", **kw) -> int:
    return conn.execute(insert(models.review_items).values(
        tenant_id="pai", kind="collect", dedupe_key=key, **kw).returning(models.review_items.c.id)).scalar()


def test_database_rules(engine, clean):
    with engine.begin() as conn:
        rid = _reviewer(conn)
        item = _item(conn)
        conn.execute(insert(models.fact_reviews).values(tenant_id="pai", item_id=item, reviewer_id=rid, step="check",
                                                        outcome="correct"))
    for kw in ({"ref": "amina", "token": "h2"}, {"ref": "x", "token": "h1"}, {"ref": "y", "token": "h3", "role": "boss"}):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            _reviewer(conn, **kw) if "role" not in kw else conn.execute(insert(models.reviewers).values(
                tenant_id="pai", ref="y", display_name="y", identity="y", role="boss", token_hash="h3"))
    with pytest.raises(IntegrityError), engine.begin() as conn:  # one open item per key
        _item(conn)
    with engine.begin() as conn:
        conn.execute(models.review_items.update().values(status="closed"))
        _item(conn)  # a closed one frees the key
    with pytest.raises(IntegrityError), engine.begin() as conn:  # one review per reviewer and item
        conn.execute(insert(models.fact_reviews).values(tenant_id="pai", item_id=item, reviewer_id=rid, step="approve",
                                                        outcome="approve"))
    with pytest.raises(IntegrityError), engine.begin() as conn:  # an outcome that does not fit the step
        conn.execute(insert(models.fact_reviews).values(tenant_id="pai", item_id=item, reviewer_id=_reviewer(
            conn, "bilal", "h9"), step="approve", outcome="correct"))


# --- the policy file --------------------------------------------------------------------------------------------------

def test_policy_file_loads_with_the_owner_ruling():
    p = load_policy()
    assert p.counting_kinds == ("person", "ai") and p.min_persons == 0
    assert (p.steps_high_stakes, p.steps_other) == (2, 1)
    assert "ocr" in p.compare_with_original and p.collect_needs_evidence


def test_policy_is_checked():
    data = yaml.safe_load(Path(POLICY_FILE).read_text())
    for change in ({"counting_kinds": []}, {"counting_kinds": ["robot"]}, {"min_persons": 1, "counting_kinds": ["ai"]},
                   {"steps_high_stakes": 3}):
        with pytest.raises(ValueError):
            parse({**data, **change})
    assert replace(parse(data), min_persons=0) == parse(data)
