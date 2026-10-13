import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.os.contracts.route_contract import RouteContract, export_json_schema

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "app" / "os" / "contracts" / "route_contract.v1.schema.json"


def valid(**over):
    base = {"contract_version": "1", "source": "self_serve", "external_ref": "ext-1",
            "student_ref": "stu-1", "origin_country": "PK", "destination_country": "DE",
            "level": "master", "target_intake": {"term": "winter", "year": 2027},
            "programmes": [{"programme_ref": "prog-a", "rank": 1}, {"programme_ref": "prog-b", "rank": 2}]}
    return {**base, **over}


def test_valid_contract_and_dedupe_key():
    c = RouteContract.model_validate(valid())
    assert c.dedupe_key == "self_serve:ext-1:1"


def test_country_codes_normalised():
    c = RouteContract.model_validate(valid(origin_country=" pk ", destination_country="de"))
    assert (c.origin_country, c.destination_country) == ("PK", "DE")


def test_same_origin_and_destination_allowed():          # local routes (D5)
    assert RouteContract.model_validate(valid(destination_country="PK")).destination_country == "PK"


@pytest.mark.parametrize("bad,msg", [
    ({"origin_country": "PAK"}, "two-letter"),
    ({"programmes": []}, "at least 1"),
    ({"programmes": [{"programme_ref": "a", "rank": 1}, {"programme_ref": "a", "rank": 2}]}, "duplicate programme"),
    ({"programmes": [{"programme_ref": "a", "rank": 1}, {"programme_ref": "b", "rank": 3}]}, "ranks must be 1..n"),
    ({"source": "partner"}, "source"),
    ({"unexpected": 1}, "Extra inputs"),
])
def test_rejections(bad, msg):
    with pytest.raises(ValidationError, match=msg):
        RouteContract.model_validate(valid(**bad))


def test_schema_is_frozen():
    committed = json.loads(SCHEMA_PATH.read_text())
    assert export_json_schema() == committed, "Contract changed: bump contract_version and add a new schema file"
