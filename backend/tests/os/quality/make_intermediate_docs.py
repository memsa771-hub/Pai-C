"""The Spike 2 intermediate set (P3-T8, ADR-001 D13, R-40): fictional documents of the seven new document types.

Three "same person" bundles, one document of each new type per person, each page marked "SAMPLE - TEST DOCUMENT".
The people are invented, and every issuer is a fictional office on a `.test` domain. Values are only the fields the
types define (the minimal identity fields, plus the identity number and the equivalent level the D13 citations
support). Planted findings:
- bundle i2: the fee receipt is for another person (a full-name mismatch);
- bundle i3: a spelling variant of the full name on the migration certificate (Muhammad / Mohammad);
- bundle i1 is consistent.

Deterministic: the same Pillow gives the same bytes. The key (`intermediate_key.yaml`) is written from the same data,
so it is exact by construction. Scoring runs offline with the runner's test model (`--set intermediate`); a scored
run with a real reader waits for the owner's testing phase (ADR-001 Q6: no billed run).

    python -m tests.os.quality.make_intermediate_docs --out tests/os/fixtures/documents/intermediate

Test code: country-specific words are allowed here (invariant 12 covers app/os only).
"""

import argparse
import io
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw

from tests.os.quality.make_sample_docs import MARK, PAGE, _font

INTERMEDIATE = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "intermediate"
KEY_NAME = "intermediate_key.yaml"
NEW_TYPES = ("national_identity_card", "equivalence_certificate", "o_a_level_statement", "domicile_certificate",
             "character_certificate", "migration_certificate", "fee_challan_receipt")
LABELS = {
    "national_identity_card": "NATIONAL IDENTITY CARD (SAMPLE)", "equivalence_certificate": "EQUIVALENCE CERTIFICATE",
    "o_a_level_statement": "STATEMENT OF RESULTS (SAMPLE GCE)", "domicile_certificate": "DOMICILE CERTIFICATE",
    "character_certificate": "CHARACTER CERTIFICATE", "migration_certificate": "MIGRATION CERTIFICATE",
    "fee_challan_receipt": "FEE PAYMENT RECEIPT",
}
ISSUERS = {
    "national_identity_card": "Sample Identity Office (identity.test)",
    "equivalence_certificate": "Sample Equivalence Office (equivalence.test)",
    "o_a_level_statement": "Sample Examinations Body (exams.test)",
    "domicile_certificate": "Sample District Office (district-a.test)",
    "character_certificate": "Exampleton Model College (college-a.test)",
    "migration_certificate": "Sample Board of Education (board-a.test)",
    "fee_challan_receipt": "Sample Bank, Exampleton Branch (bank.test)",
}
PEOPLE = {
    "i1": {"name": "Sana Testwala", "level": "Secondary School Certificate"},
    "i2": {"name": "Omar Fixture", "level": "Higher Secondary School Certificate", "fee_name": "Bilal Placeholder"},
    "i3": {"name": "Muhammad Danish Sample", "level": "Secondary School Certificate",
           "migration_name": "Mohammad Danish Sample"},
}
EXPECT = {
    "i1": [],
    "i2": [{"kind": "mismatch", "field": "full_name"}],
    "i3": [{"kind": "variant", "field": "full_name"}],
}


def documents() -> dict[str, dict]:
    """Every intermediate sample: file name -> {type, person, fields}. Fields not listed are absent (null)."""
    out: dict[str, dict] = {}
    for n, (b, p) in enumerate(PEOPLE.items(), 1):
        for t in NEW_TYPES:
            name = p.get("fee_name") if t == "fee_challan_receipt" else p.get("migration_name") \
                if t == "migration_certificate" else None
            fields: dict = {"holder_name": name or p["name"], "issuing_authority": ISSUERS[t]}
            if t == "national_identity_card":
                fields["identity_number"] = f"00000-000000{n}-{n}"  # all-zero block: not a real number format
            if t == "equivalence_certificate":
                fields["equivalent_level"] = p["level"]
            out[f"{b}_{t}.png"] = {"type": t, "person": b, "fields": fields}
    return out


def render(name: str, doc: dict) -> bytes:
    img = Image.new("RGB", PAGE, (252, 252, 248))
    d = ImageDraw.Draw(img)
    w, h = img.size
    d.rectangle((12, 12, w - 13, h - 13), outline=(60, 60, 90), width=3)
    d.text((40, 30), MARK, font=_font(30), fill=(200, 30, 30))
    d.text((40, 80), LABELS[doc["type"]], font=_font(40), fill=(20, 20, 60))
    y = 150
    for key, value in doc["fields"].items():
        d.text((40, y), f"{key.replace('_', ' ').capitalize()}:", font=_font(24), fill=(90, 90, 90))
        d.text((300, y), str(value), font=_font(26), fill=(10, 10, 10))
        y += 62
    d.text((w - 420, h - 50), MARK, font=_font(22), fill=(200, 30, 30))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=False, compress_level=9)
    return out.getvalue()


def key_data() -> dict:
    """Every field of each type is listed, `null` where the document does not show it."""
    from app.os.documents.types import load_document_types

    types = load_document_types()
    docs = {name: {**d, "fields": {f.name: d["fields"].get(f.name) for f in types[d["type"]].fields}}
            for name, d in documents().items()}
    return {"verified": True,  # generated together with the images, so it is exact
            "documents": docs,
            "bundles": {b: {"expect": e} for b, e in EXPECT.items()}}


def write(out: Path) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, doc in documents().items():
        (out / name).write_bytes(render(name, doc))
        written.append(out / name)
    (out / KEY_NAME).write_text(yaml.safe_dump(key_data(), sort_keys=True, allow_unicode=True), encoding="utf-8")
    return written + [out / KEY_NAME]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=INTERMEDIATE)
    args = ap.parse_args(argv)
    print(f"wrote {len(write(args.out))} files to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
