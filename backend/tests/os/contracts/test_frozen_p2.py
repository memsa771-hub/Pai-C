"""P2-T1: the P2 contracts programme_facts.v1, merit_check.v1 and programme_list.v2 (P2 spec P2-D27; master §9.1,
R-23, R-25, R-26, R-31). Frozen once merged: a change is a new version file. Fictional data only."""

import copy
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.os.contracts.merit_check import MeritCheckV1
from app.os.contracts.programme_facts import ProgrammeFactsV1
from app.os.contracts.programme_list import ProgrammeEntry
from app.os.contracts.programme_list_v2 import ProgrammeEntryV2, ProgrammeListV2

pytestmark = pytest.mark.req("R-23")

CONTRACTS = Path(__file__).resolve().parents[3] / "app" / "os" / "contracts"
SAMPLES = CONTRACTS / "samples" / "p2"
MODELS = {"programme_facts.v1": ProgrammeFactsV1, "merit_check.v1": MeritCheckV1,
          "programme_list.v2": ProgrammeListV2}
SCHEMA_SHA256 = {
    "programme_facts.v1": "b185515934fd4c5f567e15d0a02a9d25a2cc268209dbdd9a72b79aa00fe42a5f",
    "merit_check.v1": "7a7057b29173909fef92781c3130d5f937c79a3f91187115649b371fbfe5c8f4",
    "programme_list.v2": "62bc2c6e0d28d0485fd17e9edabf10ba306ff64538c8dc4b7aafc7e868348bcf",
}


def sample(name: str) -> dict:
    return json.loads((SAMPLES / name).read_text())


@pytest.mark.parametrize("stem", sorted(MODELS))
def test_schema_files_match_models(stem):
    committed = json.loads((CONTRACTS / f"{stem}.schema.json").read_text())
    assert MODELS[stem].model_json_schema() == committed, f"{stem} changed: add a new version file instead"


@pytest.mark.parametrize("stem", sorted(MODELS))
def test_schema_literals(stem):
    name, version = stem.rsplit(".", 1)
    assert MODELS[stem].model_json_schema()["properties"]["schema"]["const"] == f"pai.{name}.{version}"


@pytest.mark.parametrize("stem", sorted(MODELS))
def test_schema_file_hash_pinned(stem):
    got = hashlib.sha256((CONTRACTS / f"{stem}.schema.json").read_bytes()).hexdigest()
    assert got == SCHEMA_SHA256[stem], f"{stem} changed: add a new version file instead"


def test_samples_validate():
    listed = yaml.safe_load((SAMPLES / "valid.yaml").read_text())
    assert {e["file"] for e in listed} == {p.name for p in SAMPLES.glob("*.json")}
    for entry in listed:
        MODELS[entry["contract"]].model_validate(sample(entry["file"]))


def facts_with(index: int, **over) -> dict:
    d = sample("programme_facts_alpha.json")
    d["facts"][index] = {**d["facts"][index], **over}
    return d


@pytest.mark.req("R-25")
@pytest.mark.parametrize("index,over,match", [
    (0, {"source": None}, "needs its source"),
    (2, {"value": 1000}, "carries no value"),
    (4, {"fact_intake": {"term": "fall", "year": 2027}}, "no source or intake"),
    (0, {"level": "confirmed"}, "only when verified"),
])
def test_programme_facts_level_rules(index, over, match):
    with pytest.raises(ValidationError, match=match):
        ProgrammeFactsV1.model_validate(facts_with(index, **over))


@pytest.mark.req("R-26")
def test_other_intake_must_be_flagged():
    with pytest.raises(ValidationError, match="other_intake"):
        ProgrammeFactsV1.model_validate(facts_with(1, other_intake=False))
    with pytest.raises(ValidationError, match="other_intake"):
        ProgrammeFactsV1.model_validate(facts_with(0, other_intake=True))


def test_duplicate_field_rejected():
    d = sample("programme_facts_alpha.json")
    d["facts"].append(copy.deepcopy(d["facts"][0]))
    with pytest.raises(ValidationError, match="duplicate field"):
        ProgrammeFactsV1.model_validate(d)


@pytest.mark.req("R-31")
def test_merit_computed_needs_verified_formula():
    d = sample("merit_check_computed.json")
    d["formula"]["level"] = "confirmed"
    with pytest.raises(ValidationError, match="verified formula"):
        MeritCheckV1.model_validate(d)


@pytest.mark.req("R-31")
def test_merit_rules():
    d = sample("merit_check_computed.json")
    with pytest.raises(ValidationError, match="must name its list"):
        MeritCheckV1.model_validate({**d, "closing_merits": [{**d["closing_merits"][0], "list_number": None}]})
    with pytest.raises(ValidationError, match="add up to 1"):
        bad = copy.deepcopy(d)
        bad["formula"]["parts"][0]["weight"] = 0.4
        MeritCheckV1.model_validate(bad)
    n = sample("merit_check_not_confirmed.json")
    with pytest.raises(ValidationError, match="no aggregate"):
        MeritCheckV1.model_validate({**n, "aggregate": 50})
    with pytest.raises(ValidationError, match="missing part"):
        MeritCheckV1.model_validate({**n, "status": "missing"})


@pytest.mark.req("R-31")
def test_merit_never_predicts():
    def names(schema) -> set[str]:
        out = set()
        if isinstance(schema, dict):
            for k, v in schema.items():
                if k == "properties":
                    out |= set(v)
                out |= names(v)
        elif isinstance(schema, list):
            for v in schema:
                out |= names(v)
        return out
    words = ("chance", "probab", "predict", "likely", "odds")
    assert not [n for n in names(MeritCheckV1.model_json_schema()) if any(w in n for w in words)]


def test_programme_list_v2_keeps_v1_fields():
    assert set(ProgrammeEntry.model_fields) <= set(ProgrammeEntryV2.model_fields)
    with pytest.raises(ValidationError):
        ProgrammeListV2.model_validate({**sample("programme_list_v2.json"), "schema": "pai.programme_list.v1"})


@pytest.mark.req("R-25")
def test_closing_merit_value_only_when_verified():
    d = sample("merit_check_computed.json")
    cm = d["closing_merits"][0]
    with pytest.raises(ValidationError, match="only when verified"):
        MeritCheckV1.model_validate({**d, "closing_merits": [{**cm, "level": "confirmed"}]})
    ok = MeritCheckV1.model_validate({**d, "closing_merits": [{**cm, "level": "not_confirmed", "value": None}]})
    assert ok.closing_merits[0].value is None
