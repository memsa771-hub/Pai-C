"""The Spike 2 sample set (Slice 3 spec S3-D12, plan Task 10): fictional documents for the document pipeline.

Five "same person" bundles of the six document types, each page marked "SAMPLE – TEST DOCUMENT". The people and
institutions are invented. Planted findings:
- bundle 2: a spelling variant of the full name (Muhammad / Mohammad);
- bundle 3: a different father's name on the transcript;
- bundle 4: a different date of birth on the HSSC certificate (day and month swapped);
- bundles 1 and 5 are consistent.
Two extra pages test hard input: bundle 1's passport rotated 90 degrees, and bundle 5's transcript at low
resolution.

Deterministic: the same Pillow gives the same bytes. The key (`samples_key.yaml`) is written from the same data, so
it is exact by construction.

    python -m tests.os.quality.make_sample_docs --out tests/os/fixtures/documents/samples

Test code: country-specific words are allowed here (invariant 12 covers app/os only).
"""

import argparse
import io
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

from app.os.documents.validators import check_digit

SAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "documents" / "samples"
KEY_NAME = "samples_key.yaml"
MARK = "SAMPLE - TEST DOCUMENT"  # spec: "SAMPLE – TEST DOCUMENT"; the built-in font has no en dash
PAGE = (1000, 1414)  # A4 portrait
CARD = (1250, 880)  # a passport data page

PEOPLE = {
    "b1": {"given": "Sara Ahmed", "surname": "Khan", "father": "Ahmed Raza Khan", "dob": "2001-04-12", "sex": "F"},
    "b2": {"given": "Muhammad Bilal", "surname": "Qureshi", "father": "Tariq Qureshi", "dob": "2000-09-05",
           "sex": "M", "degree_given": "Mohammad Bilal"},
    "b3": {"given": "Ayesha", "surname": "Noor", "father": "Javed Iqbal", "dob": "2002-01-20", "sex": "F",
           "transcript_father": "Nasir Iqbal"},
    "b4": {"given": "Hamza Ali", "surname": "Shah", "father": "Imran Shah", "dob": "1999-07-03", "sex": "M",
           "hssc_dob": "1999-03-07"},
    "b5": {"given": "Zainab Fatima", "surname": "Malik", "father": "Khalid Malik", "dob": "2001-11-30", "sex": "F"},
}
EXPECT = {
    "b1": [],
    "b2": [{"kind": "variant", "field": "full_name"}],
    "b3": [{"kind": "mismatch", "field": "father_name"}],
    "b4": [{"kind": "mismatch", "field": "date_of_birth"}],
    "b5": [],
}
LABELS = {
    "passport": "PASSPORT", "degree_certificate": "DEGREE", "transcript": "TRANSCRIPT OF ACADEMIC RECORD",
    "ssc_certificate": "SECONDARY SCHOOL CERTIFICATE", "hssc_certificate": "HIGHER SECONDARY SCHOOL CERTIFICATE",
    "ielts_trf": "TEST REPORT FORM (SAMPLE ENGLISH TEST)",
}


def _mrz(p: dict, number: str, expiry: str) -> tuple[str, str]:
    """ICAO 9303 TD3 lines for a fictional passport (country code ZZZ is reserved for tests)."""
    names = f"{p['surname'].upper()}<<{p['given'].upper().replace(' ', '<')}"
    line1 = f"P<ZZZ{names}".ljust(44, "<")[:44]
    num = number.ljust(9, "<")
    birth, exp = p["dob"][2:].replace("-", ""), expiry[2:].replace("-", "")
    personal = "<" * 14
    parts = [num + check_digit(num), "ZZZ", birth + check_digit(birth), p["sex"], exp + check_digit(exp),
             personal + check_digit(personal)]
    body = "".join(parts)
    composite = body[0:10] + body[13:20] + body[21:43]
    return line1, body + check_digit(composite)


def documents() -> dict[str, dict]:
    """Every sample document: file name -> {type, person, fields}. Fields not listed are absent (null)."""
    out: dict[str, dict] = {}
    for n, (b, p) in enumerate(PEOPLE.items(), 1):
        full = f"{p['given']} {p['surname']}"
        number, expiry = f"ZS{n}04{n}7{n}9", f"203{n}-0{n}-1{n}"
        line1, line2 = _mrz(p, number, expiry)
        out[f"{b}_passport.png"] = {"type": "passport", "person": b, "fields": {
            "surname": p["surname"].upper(), "given_names": p["given"].upper(), "nationality": "SAMPLELAND",
            "country_code": "ZZZ", "date_of_birth": p["dob"], "sex": p["sex"], "place_of_birth": "EXAMPLE CITY",
            "passport_number": number, "issue_date": f"202{n}-0{n}-1{n}", "expiry_date": expiry,
            "mrz_line1": line1, "mrz_line2": line2}}
        degree_name = f"{p.get('degree_given', p['given'])} {p['surname']}"
        out[f"{b}_degree_certificate.png"] = {"type": "degree_certificate", "person": b, "fields": {
            "student_name": degree_name, "father_name": p["father"], "institution": "University of Exampleton",
            "degree_title": "Bachelor of Science in Computer Science", "session": f"201{n + 4}-20{n + 18}",
            "completion_date": f"202{n - 1}-07-1{n}", "registration_number": f"UOE-{n}0{n}4-CS",
            "cgpa": round(3.0 + n / 10, 2), "cgpa_scale": 4.0}}
        out[f"{b}_transcript.png"] = {"type": "transcript", "person": b, "fields": {
            "student_name": degree_name, "father_name": p.get("transcript_father", p["father"]),
            "date_of_birth": p["dob"], "institution": "University of Exampleton",
            "degree_title": "Bachelor of Science in Computer Science", "registration_number": f"UOE-{n}0{n}4-CS",
            "cgpa": round(3.0 + n / 10, 2), "cgpa_scale": 4.0, "credit_hours": 130 + n,
            "issue_date": f"202{n - 1}-08-0{n}"}}
        for kind, year, total in (("ssc_certificate", 2015 + n, 1100), ("hssc_certificate", 2017 + n, 1100)):
            dob = p.get("hssc_dob", p["dob"]) if kind == "hssc_certificate" else p["dob"]
            out[f"{b}_{kind}.png"] = {"type": kind, "person": b, "fields": {
                "student_name": full, "father_name": p["father"], "date_of_birth": dob,
                "board": "Board of Sample Education, Exampleton", "exam_year": str(year),
                "roll_number": f"{n}{year}{n}", "institution": "Exampleton Model School",
                "marks_obtained": 900 + 10 * n, "marks_total": total}}
        bands = [6.5 + (n % 3) * 0.5, 7.0, 6.5, 7.0]  # the overall is their band-rounded mean
        out[f"{b}_ielts_trf.png"] = {"type": "ielts_trf", "person": b, "fields": {
            "module": "Academic", "family_name": p["surname"].upper(), "first_name": p["given"].upper(),
            "date_of_birth": p["dob"], "sex": p["sex"], "test_date": f"2024-0{n}-1{n}",
            "listening": bands[0], "reading": bands[1], "writing": bands[2], "speaking": bands[3],
            "overall": _band_mean(bands), "trf_number": f"24ZZ00{n}{n}{n}SAMP{n}0{n}A"}}
    out["b1_passport_rotated.png"] = {**out["b1_passport.png"], "variant_of": "b1_passport.png"}
    out["b5_transcript_lowres.jpg"] = {**out["b5_transcript.png"], "variant_of": "b5_transcript.png"}
    return out


def _band_mean(bands: list[float]) -> float:
    mean = sum(bands) / len(bands)
    whole, frac = int(mean), mean - int(mean)
    return whole + (0.0 if frac < 0.25 else 0.5 if frac < 0.75 else 1.0)


def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.load_default(size=size)


def render(name: str, doc: dict) -> bytes:
    t, fields = doc["type"], doc["fields"]
    card = t == "passport"
    img = Image.new("RGB", CARD if card else PAGE, (252, 252, 248))
    d = ImageDraw.Draw(img)
    w, h = img.size
    d.rectangle((12, 12, w - 13, h - 13), outline=(60, 60, 90), width=3)
    d.text((40, 30), MARK, font=_font(30), fill=(200, 30, 30))
    d.text((40, 80), LABELS[t], font=_font(40), fill=(20, 20, 60))
    y = 150
    mrz = [k for k in ("mrz_line1", "mrz_line2") if k in fields]
    for key, value in fields.items():
        if key in mrz:
            continue
        label = key.replace("_", " ").capitalize()
        d.text((40, y), f"{label}:", font=_font(24), fill=(90, 90, 90))
        d.text((360, y), str(value), font=_font(28), fill=(10, 10, 10))
        y += 46 if card else 62
    for i, key in enumerate(mrz):  # the machine-readable zone at the bottom, in a fixed-width look
        d.text((40, h - 130 + i * 50), fields[key], font=_font(34), fill=(0, 0, 0))
    d.text((w - 420, h - 50 if not card else 30), MARK, font=_font(22), fill=(200, 30, 30))
    if doc.get("variant_of") and name.endswith("_rotated.png"):
        img = img.rotate(90, expand=True)
    out = io.BytesIO()
    if name.endswith(".jpg"):  # the low-resolution scan
        img.resize((w * 2 // 5, h * 2 // 5), Image.Resampling.BILINEAR).save(out, "JPEG", quality=60)
    else:
        img.save(out, "PNG", optimize=False, compress_level=9)
    return out.getvalue()


def key_data() -> dict:
    """Every field of each type is listed, `null` where the document does not show it, so a reader that fills
    one in scores it as invented."""
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
    ap.add_argument("--out", type=Path, default=SAMPLES)
    args = ap.parse_args(argv)
    print(f"wrote {len(write(args.out))} files to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
