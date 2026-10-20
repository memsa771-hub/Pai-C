"""Rule-based checks of the values read from a document (spec S3-D6).

A value that fails a check is kept as read and marked `check_failed` with its reasons; the student then confirms
or corrects it. Nothing here drops a value. The MRZ checks follow ICAO 9303 (TD3, the passport format).
"""

import math
import re
from datetime import date
from typing import Any, Literal

from app.os.documents.types import DocumentType, FieldSpec, Rule

Check = Literal["ok", "check_failed", "missing"]

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MRZ_CHARS = re.compile(r"^[A-Z0-9<]+$")
MRZ_LEN = 44


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not _ISO_DATE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def check_value(spec: FieldSpec, value: Any) -> list[str]:
    """The reasons one value is wrong for its field on its own; [] when it is fine (or absent)."""
    if value is None:
        return []
    t = spec.type
    if t == "date":
        return [] if _date(value) else ["not a real date in the form YYYY-MM-DD"]
    if t in ("number", "grade", "band"):
        x = _number(value)
        if x is None:
            return ["not a number"]
        if x < 0:
            return ["negative"]
        if t == "band" and (x > 9 or x * 2 != int(x * 2)):
            return ["not a band score (0 to 9 in steps of 0.5)"]
        return []
    if not isinstance(value, str) or not value.strip():
        return ["empty"]
    if t == "code" and spec.pattern and not re.fullmatch(spec.pattern, value.strip()):
        return ["not in the expected format"]
    if t == "enum" and value not in spec.values:
        return [f"not one of {', '.join(spec.values)}"]
    if t == "mrz_line" and (len(value) != MRZ_LEN or not _MRZ_CHARS.match(value)):
        return [f"not a machine-readable line ({MRZ_LEN} characters of A-Z, 0-9 and <)"]
    return []


# --- MRZ (ICAO 9303) -------------------------------------------------------------------------------------------


def check_digit(s: str) -> str:
    """The 7-3-1 weighted check digit: digits as themselves, A-Z as 10-35, '<' as 0."""
    total = 0
    for i, c in enumerate(s):
        v = int(c) if c.isdigit() else (ord(c) - 55 if "A" <= c <= "Z" else 0)
        total += v * (7, 3, 1)[i % 3]
    return str(total % 10)


def mrz_check(line1: str, line2: str) -> list[str]:
    for n, line in (("first", line1), ("second", line2)):
        if len(line) != MRZ_LEN or not _MRZ_CHARS.match(line):
            return [f"the {n} machine-readable line is not {MRZ_LEN} characters of A-Z, 0-9 and <"]
    if not line1.startswith("P"):
        return ["the first machine-readable line does not start with P"]
    reasons = []
    for label, data, digit in (("document number", line2[0:9], line2[9]), ("date of birth", line2[13:19], line2[19]),
                               ("expiry date", line2[21:27], line2[27])):
        if check_digit(data) != digit:
            reasons.append(f"the {label} check digit does not match")
    personal, pd = line2[28:42], line2[42]
    if not (pd == "<" and set(personal) == {"<"}) and check_digit(personal) != pd:
        reasons.append("the personal number check digit does not match")
    if check_digit(line2[0:10] + line2[13:20] + line2[21:43]) != line2[43]:
        reasons.append("the composite check digit does not match")
    return reasons


def _yymmdd(s: str, *, birth: bool) -> date | None:
    try:
        yy, mm, dd = int(s[0:2]), int(s[2:4]), int(s[4:6])
        year = 2000 + yy
        if birth and year > date.today().year:  # a birth date is never in the future
            year -= 100
        return date(year, mm, dd)
    except ValueError:
        return None


def mrz_fields(line2: str) -> dict:
    return {"number": line2[0:9].rstrip("<"), "birth": _yymmdd(line2[13:19], birth=True),
            "expiry": _yymmdd(line2[21:27], birth=False)}


# --- a whole document ------------------------------------------------------------------------------------------


def band_round(x: float) -> float:
    """IELTS overall rounding: a mean ending in .25 goes up to .5, one ending in .75 up to the next whole band."""
    return math.floor(x * 2 + 0.5) / 2


def _fmt(x: float) -> str:
    return f"{x:g}"


def validate(t: DocumentType, values: dict, today: date) -> dict[str, tuple[Check, list[str]]]:
    out: dict[str, tuple[Check, list[str]]] = {}
    for spec in t.fields:
        v = values.get(spec.name)
        if v is None or (isinstance(v, str) and not v.strip()):
            out[spec.name] = ("missing", [])
        else:
            reasons = check_value(spec, v)
            out[spec.name] = ("check_failed" if reasons else "ok", reasons)

    def usable(name: str) -> bool:
        return out[name][0] == "ok"

    def fail(name: str, reason: str) -> None:
        out[name] = ("check_failed", out[name][1] + [reason])

    for rule in t.rules:
        _apply(rule, values, today, usable, fail)
    return out


def _apply(rule: Rule, values: dict, today: date, usable, fail) -> None:
    f = rule.fields
    if rule.kind == "band_mean":
        *parts, total = f
        if all(usable(p) for p in parts + [total]):
            want = band_round(sum(_number(values[p]) for p in parts) / len(parts))
            if _number(values[total]) != want:
                fail(total, f"should be {_fmt(want)} from the band scores")
    elif rule.kind == "lte":
        a, b = f
        if usable(a) and usable(b) and _number(values[a]) > _number(values[b]):
            fail(a, f"greater than {b} ({_fmt(_number(values[b]))})")
    elif rule.kind == "mrz":
        line1, line2, number, birth, expiry = f
        if usable(expiry) and _date(values[expiry]) < today:
            fail(expiry, "expired")
        if not (usable(line1) and usable(line2)):
            return
        reasons = mrz_check(values[line1], values[line2])
        for r in reasons:
            fail(line2, r)
        if reasons:
            return
        m = mrz_fields(values[line2])
        disagree = "does not match the machine-readable zone"
        if usable(number) and values[number].strip() != m["number"]:
            fail(number, disagree)
        if usable(birth) and _date(values[birth]) != m["birth"]:
            fail(birth, disagree)
        if usable(expiry) and _date(values[expiry]) != m["expiry"]:
            fail(expiry, disagree)
