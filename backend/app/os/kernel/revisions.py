"""What a revision changes: a pure diff between the stored tasks and a new draft (parent §4.3)."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.os.compiler import DraftTask
from app.os.kernel.states import TERMINAL, TaskState, is_started

NOTICE_PREFIX = "plan_updated@"
CANCELLED_MARK = "#c"  # a cancelled task's instance_key becomes "<key>#c<revision>", so the key can return
DONE_MARK = "#d"  # a re-checked task's finished row becomes "<key>#d<revision>" (see `diff`, recheck_types)
REMOVED_TOKEN = "removed"

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
    rechecked: list[str] = field(default_factory=list)  # done tasks whose check is needed again (also in added)
    # key -> token of the draft difference that was reported for a started/protected task (stored on the
    # row so the same difference is reported once, not on every recompute)
    tokens: dict[str, str] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed or self.skipped_started or self.kept_protected)

    def as_json(self) -> dict:
        return {k: sorted(v) for k, v in self.__dict__.items() if k != "tokens"}


def stored_view(row: Mapping) -> dict:
    """The structural fields of a stored task, comparable with a DraftTask."""
    view = {k: row[k] for k in STRUCTURAL if k != "latest_finish"}
    view["latest_finish"] = row["due_at"]
    return view


def draft_view(t: DraftTask) -> dict:
    return {k: getattr(t, k) for k in STRUCTURAL}


def draft_token(t: DraftTask) -> str:
    """Identifies one version of a task in a draft (its structural fields and dependencies)."""
    payload = {k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in draft_view(t).items()}
    payload["depends_on"] = sorted(list(d) for d in t.depends_on)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:32]


def diff(stored: Mapping[str, Mapping], draft_tasks: Mapping[str, DraftTask],
         stored_deps: Mapping[str, set], recheck_types: frozenset[str] = frozenset()) -> RevisionDiff:
    """A task that has started (or is protected) keeps its version; the difference is reported once,
    the first time this exact draft version is seen. Finished tasks are history and never reported.

    One exception: a done task of a `recheck_types` type whose key is in the draft again (the compiler asks
    for a fact check only while the fact is not confirmed, so a stale fact asks again, spec §4.7) is
    `rechecked`: its row keeps its history under a new key and a fresh task is added."""
    d = RevisionDiff()

    def report_once(target: list[str], key: str, token: str, row: Mapping) -> None:
        if row["skipped_draft"] != token:
            target.append(key)
            d.tokens[key] = token

    for key, row in stored.items():
        if key.startswith(NOTICE_PREFIX) or CANCELLED_MARK in key or DONE_MARK in key:
            continue
        state = TaskState(row["state"])
        started = is_started(state, row["kind"])
        if key in draft_tasks and state == TaskState.DONE and row["task_type"] in recheck_types:
            d.rechecked.append(key)
            continue
        if key not in draft_tasks:
            if state in TERMINAL:
                continue
            if row["protected"]:
                report_once(d.kept_protected, key, REMOVED_TOKEN, row)
            elif started:
                report_once(d.skipped_started, key, REMOVED_TOKEN, row)
            else:
                d.removed.append(key)
            continue
        new = draft_tasks[key]
        same = stored_view(row) == draft_view(new) and stored_deps.get(key, set()) == set(new.depends_on)
        if same:
            continue
        if not started:
            d.changed.append(key)
        elif state not in TERMINAL:
            report_once(d.skipped_started, key, draft_token(new), row)
    d.added = sorted(k for k in draft_tasks if k not in stored or k in d.rechecked)
    return d
