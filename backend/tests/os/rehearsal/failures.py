"""The rehearsal failure log (Slice 9a spec §2.5): one YAML file per run, kept OUTSIDE the repo
(`~/s9-rehearsal/<run>/failures.yaml`; tests use a temporary folder).

Each entry: id, student number, step (`template_key`), expected, got, severity. Later, by hand: `fixed_by` (the PR) or
`owner_accepted` (the owners' words and date); those keys are kept when the file is read and written again. The driver
writes what it can see (a wrong state, a stuck plan, an error response, a missed expected change); one entry per id,
so a problem seen on every loop is logged once. Fictional students only: never real student data."""

from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Literal

import yaml

Severity = Literal["blocks", "workaround", "wording"]
SEVERITIES: tuple[str, ...] = ("blocks", "workaround", "wording")
HEADER = ("# Slice 9a rehearsal failure log (spec §2.5). Written by tests/os/rehearsal/driver.py; add `fixed_by` or\n"
          "# `owner_accepted` to an entry by hand. Fictional students only.\n")


@dataclass(frozen=True)
class Failure:
    id: str
    student: str
    step: str | None
    expected: str
    got: str
    severity: Severity

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity {self.severity!r}")


_KEYS = tuple(f.name for f in fields(Failure))


class FailureLog:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._raw: list[dict] = []
        if self.path.exists():
            self._raw = (yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}).get("failures") or []

    def add(self, failure: Failure) -> bool:
        """Adds the entry and writes the file at once (a crashed run keeps what it found). False if its id is in."""
        if any(r["id"] == failure.id for r in self._raw):
            return False
        self._raw.append(asdict(failure))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(HEADER + yaml.safe_dump({"failures": self._raw}, sort_keys=False, allow_unicode=True),
                             encoding="utf-8")
        return True

    def entries(self) -> list[Failure]:
        return [Failure(**{k: r.get(k) for k in _KEYS}) for r in self._raw]

    def counts(self) -> dict[str, int]:
        """Entries per severity (only the severities that occur)."""
        out: dict[str, int] = {}
        for f in self.entries():
            out[f.severity] = out.get(f.severity, 0) + 1
        return out
