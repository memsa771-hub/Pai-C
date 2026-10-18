"""What a revision changes: a pure diff between the stored tasks and a new draft (parent §4.3)."""

from collections.abc import Mapping
from dataclasses import dataclass, field

from app.os.compiler import DraftTask
from app.os.kernel.states import UNSTARTED, TaskState

NOTICE_PREFIX = "plan_updated@"

# Fields whose change is a structural revision. earliest_start, slack and critical drift with "today"
# and are refreshed in place without a revision.
STRUCTURAL = (
    "template_key", "task_type", "kind", "inbox_kind", "programme_ref", "title", "duration_days",
    "latest_start", "latest_finish", "due_tz", "provisional", "estimated", "blocked_reason", "protected",
)


@dataclass
class RevisionDiff:
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    skipped_started: list[str] = field(default_factory=list)
    kept_protected: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.skipped_started or self.kept_protected)

    def as_json(self) -> dict:
        return {k: sorted(v) for k, v in self.__dict__.items()}


def stored_view(row: Mapping) -> dict:
    """The structural fields of a stored task, comparable with a DraftTask."""
    view = {k: row[k] for k in STRUCTURAL if k != "latest_finish"}
    view["latest_finish"] = row["due_at"]
    return view


def draft_view(t: DraftTask) -> dict:
    return {k: getattr(t, k) for k in STRUCTURAL}


def diff(stored: Mapping[str, Mapping], draft_tasks: Mapping[str, DraftTask],
         stored_deps: Mapping[str, set], ) -> RevisionDiff:
    d = RevisionDiff()
    for key, row in stored.items():
        if key.startswith(NOTICE_PREFIX):
            continue
        started = TaskState(row["state"]) not in UNSTARTED
        if key not in draft_tasks:
            if row["protected"]:
                d.kept_protected.append(key)
            elif started:
                if TaskState(row["state"]) not in (TaskState.DONE, TaskState.SKIPPED, TaskState.CANCELLED):
                    d.skipped_started.append(key)
            elif TaskState(row["state"]) != TaskState.CANCELLED:
                d.removed.append(key)
            continue
        new = draft_tasks[key]
        same = stored_view(row) == draft_view(new) and stored_deps.get(key, set()) == set(new.depends_on)
        if not same:
            (d.skipped_started if started else d.changed).append(key)
    d.added = sorted(k for k in draft_tasks if k not in stored)
    return d
