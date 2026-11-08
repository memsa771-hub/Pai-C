"""The Spike 1 rerun harness per region (P2 spec §9 item 7, P2-D30; master §12).

The rerun asks: for a sample of institutions of each region, are the high-stakes facts the system holds right? An answer key
(`tests/os/quality/<region>_answer_key.yaml`, made by a checker who did not verify those rows, H6) names each fact and its
right value. The harness **scores what the system holds against the key**; it never researches, fetches or calls a model, so
scoring costs nothing. The research run that fills the facts is separate and billed (cost cap in the owner's ruling Q5);
`plan` says what it would need and whether it fits the cap, without running it.

Bars (master §12): 100% correct among `verified` facts, at least 95% among `confirmed` facts. A key entry with no fact is
`missing`; a fact below `confirmed` is `not_confirmed`. Neither counts as correct, and both are listed.

Answer-key file shape (nothing country-specific in the code; the region code is a key of regions.yaml):

    version: 1
    region: <region code>
    intake: {term: <term>, year: <year>}
    checker: <the checker who did not verify these rows>
    entries:
      - {scope: programme|registry|route, ref: <ref>, field: <field>, value: <the right value>, owner_ref: ""}
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import Engine, select

from app.os import models
from app.os.knowledge.fact_classes import fact_class, is_high_stakes
from app.os.knowledge.regions import regions

K = models.knowledge_facts
KEY_DIR = Path(__file__).resolve().parents[3] / "tests" / "os" / "quality"
BAR_VERIFIED, BAR_CONFIRMED = 1.0, 0.95
SAMPLE_PER_REGION = 5  # P2-D30: institutions per region
SCOPES = ("programme", "registry", "route")


class KeyError_(ValueError):
    """An answer key that is not valid."""


@dataclass(frozen=True)
class KeyEntry:
    scope: str
    ref: str
    field: str
    value: Any
    owner_ref: str = ""


@dataclass(frozen=True)
class AnswerKey:
    region: str
    term: str
    year: int
    checker: str
    entries: tuple[KeyEntry, ...]

    @property
    def refs(self) -> set[str]:
        return {e.ref for e in self.entries}


def load_key(path: Path) -> AnswerKey:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    for k in ("region", "intake", "checker", "entries"):
        if not raw.get(k):
            raise KeyError_(f"{Path(path).name}: '{k}' is required")
    region = str(raw["region"])
    if region not in {r.code for c in _countries() for r in regions(c)}:
        raise KeyError_(f"{Path(path).name}: unknown region '{region}'")
    intake = raw["intake"]
    entries = []
    for i, e in enumerate(raw["entries"], 1):
        if e.get("scope") not in SCOPES or not e.get("ref") or not e.get("field") or "value" not in e:
            raise KeyError_(f"{Path(path).name}: entry {i} needs scope, ref, field and value")
        entries.append(KeyEntry(e["scope"], str(e["ref"]), str(e["field"]), e["value"], str(e.get("owner_ref") or "")))
    return AnswerKey(region, str(intake.get("term") or ""), int(intake["year"]), str(raw["checker"]), tuple(entries))


def _countries() -> list[str]:
    from app.os.knowledge.regions import countries

    return countries()


def keys_in(directory: Path = KEY_DIR) -> dict[str, Path]:
    """The answer keys on disk, by region: files named `<region>_answer_key.yaml`."""
    return {p.name.removesuffix("_answer_key.yaml"): p for p in sorted(Path(directory).glob("*_answer_key.yaml"))
            if p.name != "spike1_answer_key.yaml"}


def normal(value: Any) -> Any:
    """A value in the form it is compared in: text trimmed and case-folded, a number as a float, a `{value: x}` wrapper
    unwrapped (the import writes `{"value": ..., "unit": ..., "date": ...}`), containers recursively."""
    if isinstance(value, dict):
        if "value" in value and set(value) <= {"value", "unit", "date", "tz"}:
            return normal(value["value"])
        return {k: normal(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [normal(v) for v in value]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = " ".join(value.split()).casefold()
        try:
            return float(text.replace(",", ""))
        except ValueError:
            return text
    return value


@dataclass
class Score:
    region: str
    checked: int = 0
    by_level: dict[str, dict[str, int]] = field(default_factory=lambda: {
        "verified": {"held": 0, "correct": 0}, "confirmed": {"held": 0, "correct": 0}})
    wrong: list[dict] = field(default_factory=list)  # codes and refs only
    missing: list[dict] = field(default_factory=list)
    not_confirmed: list[dict] = field(default_factory=list)
    institutions: int = 0

    def rate(self, level: str) -> float | None:
        held = self.by_level[level]["held"]
        return None if held == 0 else self.by_level[level]["correct"] / held

    @property
    def passed(self) -> bool:
        """The bars hold, and there is something to hold them to: a sample of institutions, and at least one verified fact."""
        v, c = self.rate("verified"), self.rate("confirmed")
        return (self.institutions >= SAMPLE_PER_REGION and v is not None and v >= BAR_VERIFIED
                and (c is None or c >= BAR_CONFIRMED))

    def as_dict(self) -> dict:
        return {"region": self.region, "checked": self.checked, "institutions": self.institutions,
                "verified": {**self.by_level["verified"], "rate": self.rate("verified")},
                "confirmed": {**self.by_level["confirmed"], "rate": self.rate("confirmed")},
                "wrong": self.wrong, "missing": self.missing, "not_confirmed": self.not_confirmed, "passed": self.passed}


def score_key(engine: Engine, tenant_id: str, key: AnswerKey) -> Score:
    """Compares the facts held with the key. Only high-stakes entries are scored against the 100% bar through `verified`;
    every entry's fact is looked up for its intake (the key's term and year) and owner."""
    score = Score(key.region)
    score.institutions = len({e.ref for e in key.entries})
    held: dict[tuple[str, str, str, str], Any] = {}
    with engine.connect() as conn:
        rows = conn.execute(select(K).where(
            K.c.tenant_id == tenant_id, K.c.intake_year == key.year, K.c.intake_term.in_([key.term, ""]),
            K.c.ref.in_(sorted(key.refs))).order_by(K.c.id)).all()
    for r in rows:  # the key's term beats an unrecorded one; then the newest
        k = (r.scope, r.ref, r.field, r.owner_ref)
        if k not in held or (r.intake_term == key.term) >= (held[k].intake_term == key.term):
            held[k] = r
    for e in key.entries:
        score.checked += 1
        row = held.get((e.scope, e.ref, e.field, e.owner_ref))
        ref = {"scope": e.scope, "ref": e.ref, "field": e.field}
        if row is None or row.value is None:
            score.missing.append(ref)
        elif row.status not in ("verified", "confirmed"):
            score.not_confirmed.append({**ref, "status": row.status})
        else:
            level = score.by_level[row.status]
            level["held"] += 1
            if normal(row.value) == normal(e.value):
                level["correct"] += 1
            else:
                score.wrong.append({**ref, "status": row.status})
    return score


def plan(key: AnswerKey, *, cost_per_fact_usd: float, spent_usd: float = 0.0, cap_usd: float = 20.0) -> dict:
    """What the billed research run for this key would need, without running it: the institutions, the fields, and the
    estimate against the cap (the owner's US$20 for all of P2, Q5). The caller supplies the unit cost."""
    cost = round(len(key.entries) * cost_per_fact_usd, 4)
    return {"region": key.region, "institutions": sorted(key.refs), "facts": len(key.entries),
            "high_stakes_facts": sum(1 for e in key.entries if is_high_stakes(fact_class(e.field))),
            "estimated_cost_usd": cost, "spent_usd": spent_usd, "cap_usd": cap_usd,
            "within_cap": spent_usd + cost <= cap_usd}


def region_coverage(keys: dict[str, AnswerKey], needed: list[str]) -> dict[str, list[str]]:
    """Which of the `needed` regions have a valid key and which are missing: the rerun runs on every region."""
    return {"with_key": sorted(set(needed) & set(keys)), "missing": sorted(set(needed) - set(keys))}
