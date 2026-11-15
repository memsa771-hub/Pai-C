"""P3-T8: the R-40 document types of the intermediate family, as data (ADR-001 D13), and their Spike 2 sample set."""

import json
import re
from datetime import date
from pathlib import Path

import pytest
import yaml

from app.os.documents.checks import cross_check, load_name_variants
from app.os.documents.types import TYPES_DIR, FieldSpec, load_document_types, reading_model
from app.os.documents.validators import validate
from tests.os.quality import make_intermediate_docs as inter
from tests.os.quality.run_document_quality import bundle_verdict, main
from tests.os.test_invariants import COUNTRY_TERMS

pytestmark = pytest.mark.req("R-40")

TYPES = load_document_types()
IDENTITY = {"holder_name", "issuing_authority"}  # the minimal identity fields every such document has
NEW = {
    "national_identity_card": IDENTITY | {"identity_number"},  # SI-11, N-37
    "equivalence_certificate": IDENTITY | {"equivalent_level"},  # II-08 ("at the relevant level"), N-32, N-34
    "o_a_level_statement": IDENTITY,
    "domicile_certificate": IDENTITY,
    "character_certificate": IDENTITY,
    "migration_certificate": IDENTITY,
    "fee_challan_receipt": IDENTITY,
}
# Institution, body and portal names from the walkthroughs, on top of the R-58 country and region terms
INSTITUTION_TERMS = re.compile(
    r"\b(NADRA|CNIC|IBCC|BISE|BIEK|FDE|SECCAP|OCAS|HED|NUML|AJK|KP|ICT|GB|matric|FSc)\b", re.I)
KEY = yaml.safe_load((inter.INTERMEDIATE / inter.KEY_NAME).read_text(encoding="utf-8"))


def generic_violations(t) -> list[str]:
    """Every country, region or institution name in what the code reads of a type: its key and label, and each
    field's name, label, hint, pattern and values (comments are not read)."""
    found = []
    texts = [("key", t.key), ("label", t.label)]
    for f in t.fields:
        texts += [(f"{f.name}.{a}", v) for a in ("name", "label", "hint", "pattern") if (v := getattr(f, a))]
        texts += [(f"{f.name}.values", v) for v in f.values]
    for where, text in texts:
        for rx in (COUNTRY_TERMS, INSTITUTION_TERMS):
            if m := rx.search(text.replace("_", " ")):
                found.append(f"{t.key}.{where}: {m.group(0)}")
    return found


def test_new_types_load_from_data():
    for key, fields in NEW.items():
        t = TYPES[key]
        assert (TYPES_DIR / f"{key}.v1.yaml").is_file(), key  # data, not code
        assert t.version == 1 and {f.name for f in t.fields} == fields, key
        reading_model(t)  # the reader's output model builds from the YAML alone
        [name] = [f for f in t.fields if f.cross_check == "full_name"]
        assert name.name == "holder_name", key


def test_ssc_and_hssc_reused_unchanged():
    """D13 reuses ssc_certificate.v1 and hssc_certificate.v1: no field was added, so no v2."""
    for key in ("ssc_certificate", "hssc_certificate"):
        assert TYPES[key].version == 1 and sorted(TYPES_DIR.glob(f"{key}.v*.yaml")) == [TYPES_DIR / f"{key}.v1.yaml"]


def test_new_type_fields_are_generic():
    assert {k: generic_violations(TYPES[k]) for k in NEW} == {k: [] for k in NEW}


def test_generic_check_catches_a_name():
    from app.os.documents.types import DocumentType

    bad = DocumentType(key="id_card", version=1, label="Identity card", fields=[
        FieldSpec(name="holder_name", type="name", hint="Name as on the NADRA card"),
        FieldSpec(name="region", type="enum", hint="Where issued", values=["Punjab", "Other"]),
        FieldSpec(name="bise_roll", type="code", hint="Roll number")])
    assert generic_violations(bad) == ["id_card.holder_name.hint: NADRA", "id_card.region.values: Punjab",
                                       "id_card.bise_roll.name: bise"]


def test_no_new_vault_facts():
    """No new type maps a field to a StudentFacts key, and the Counsellor's document-to-Vault mapping does not list
    them: no cited line gives a value an existing Vault fact holds (the Vault is the Counsellor's, master §4)."""
    assert [f"{k}.{f.name}" for k in NEW for f in TYPES[k].fields if f.fact] == []
    mapping = yaml.safe_load((Path(__file__).resolve().parents[2] / "app" / "pai_c" / "connect" /
                              "document_facts.yaml").read_text(encoding="utf-8"))
    assert not set(NEW) & set(mapping["authority"])


# --- the Spike 2 intermediate set -------------------------------------------------------------------------------


def test_intermediate_set_matches_the_key_schema():
    docs = KEY["documents"]
    assert KEY["verified"] is True and set(KEY["bundles"]) == set(inter.PEOPLE)
    assert len(docs) == len(inter.PEOPLE) * len(NEW) and {d["type"] for d in docs.values()} == set(NEW)
    for name, d in docs.items():
        assert (inter.INTERMEDIATE / name).is_file(), name
        assert d["person"] in inter.PEOPLE and name == f"{d['person']}_{d['type']}.png", name
        assert set(d["fields"]) == {f.name for f in TYPES[d["type"]].fields}, name  # every field, null if absent
        assert ".test" in d["fields"]["issuing_authority"], name  # fictional issuers only
        checks = validate(TYPES[d["type"]], d["fields"], date(2026, 11, 15))
        assert {f: r for f, (c, r) in checks.items() if c == "check_failed"} == {}, name


def test_intermediate_set_deterministic(tmp_path):
    inter.write(tmp_path)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == sorted(p.name for p in inter.INTERMEDIATE.iterdir())  # the committed set is the generated one
    assert all((tmp_path / n).read_bytes() == (inter.INTERMEDIATE / n).read_bytes() for n in names)


def test_intermediate_images_carry_the_mark():
    from PIL import Image

    pngs = [p for p in inter.INTERMEDIATE.iterdir() if p.suffix == ".png"]
    assert len(pngs) == len(KEY["documents"])
    for p in pngs:
        with Image.open(p) as img:
            assert min(img.size) >= 300, p.name


def test_intermediate_planted_findings():
    variants = load_name_variants()
    found = {}
    for b in inter.PEOPLE:
        docs = [(i, TYPES[d["type"]], d["fields"]) for i, (n, d) in enumerate(sorted(KEY["documents"].items()))
                if d["person"] == b]
        found[b] = [{"kind": f.kind, "field": f.field} for f in cross_check(docs, variants)]
    assert found == {b: e["expect"] for b, e in KEY["bundles"].items()}
    assert bundle_verdict(KEY["bundles"], found) == (True, [])


def test_runner_offline_intermediate_set(tmp_path, capsys):
    """Scored locally with the runner's test model (no billed run, ADR-001 Q6). Rates and counts only."""
    out = tmp_path / "i.json"
    assert main(["--model", "test", "--set", "intermediate", "--mode", "whole", "--runs", "1", "--out", str(out)]) == 0
    result = json.loads(out.read_text(encoding="utf-8"))
    [run] = result["runs"]
    assert result["gate_passed"] and run["correct_rate"] == 1.0 and run["bundles_passed"]
    assert run["files"] == len(KEY["documents"]) and run["cost_usd"] == 0.0
    assert set(run["per_type"]) == set(NEW)
    printed = capsys.readouterr().out
    values = {str(v) for d in KEY["documents"].values() for v in d["fields"].values() if v is not None and len(str(v)) > 4}
    assert not [v for v in values if v in printed or v in out.read_text(encoding="utf-8")]
