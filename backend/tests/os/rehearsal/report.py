"""The rehearsal report (Slice 9a spec §2.4 step 5): `report.json` and a short `report.md`.

Counts and states only: per student (S1..S12) the end state, the scripted events and how each went, the rehearsal days
taken and the end points reached; totals; and the failure log's counts by severity. No names, documents or any other
personal data, even fictional."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Reached = Literal["ready_to_submit", "visa_ready"]


@dataclass
class StudentResult:
    state: str  # visa_ready | stuck | not_finished | running (a partial run)
    events: list[str] = field(default_factory=list)  # e.g. "rejected:ok", "rejected:missed"
    days: int = 0  # rehearsal days from the start date until visa_ready (or until the run stopped)
    reached: list[Reached] = field(default_factory=list)


@dataclass
class Report:
    students: dict[str, StudentResult]
    failures: dict[str, int]  # failure log entries per severity
    kills: int = 0  # worker SIGKILLs (the kill run)
    admin_actions: list[str] = field(default_factory=list)  # steps the rehearsal's admin had to take

    def totals(self) -> dict:
        states: dict[str, int] = {}
        for r in self.students.values():
            states[r.state] = states.get(r.state, 0) + 1
        return {"students": len(self.students), "states": states,
                "ready_to_submit": sum("ready_to_submit" in r.reached for r in self.students.values()),
                "visa_ready": sum("visa_ready" in r.reached for r in self.students.values()),
                "failures": sum(self.failures.values()), "kills": self.kills, "admin_actions": self.admin_actions}

    def as_json(self) -> dict:
        return {"students": {k: asdict(v) for k, v in self.students.items()}, "totals": self.totals(),
                "failures": self.failures}

    def markdown(self) -> str:
        t = self.totals()
        lines = ["# Rehearsal report", "",
                 f"Students: {t['students']}. Ready to submit: {t['ready_to_submit']}. Visa file ready: "
                 f"{t['visa_ready']}. Failures: {t['failures']} "
                 f"({', '.join(f'{k} {v}' for k, v in sorted(self.failures.items())) or 'none'}). "
                 f"Worker kills: {self.kills}. Admin steps: {', '.join(self.admin_actions) or 'none'}.", "",
                 "| student | state | days | reached | events |", "|---|---|---|---|---|"]
        for sid, r in self.students.items():
            lines.append(f"| {sid} | {r.state} | {r.days} | {', '.join(r.reached) or '-'} | "
                         f"{', '.join(r.events) or '-'} |")
        return "\n".join(lines) + "\n"

    def write(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "report.json").write_text(json.dumps(self.as_json(), indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "report.md").write_text(self.markdown(), encoding="utf-8")
