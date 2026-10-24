# -*- coding: utf-8 -*-
"""Catalog item store: one service owns every write to pai_vault_items.

Why one place: identity, the evidence ladder and the conflict order (VAULT_SPEC
§Conflicts) must be decided the same way for chat, documents and the student's
own edits. Values arrive already normalized (English, codes, ISO dates); this
module only decides what happens to them. It flushes, the caller commits.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from app.models import ProfileIssue, VaultItem, Workspace
from app.tools.schema import SchemaValidationError, validate_schema_instance

from .catalog import TypeSpec, norm, vault_catalog
from .errors import MemoryDataError
from .vault import VaultOutcome

LEVELS = ("inferred", "stated", "shown", "confirmed")
_RANK = {name: i for i, name in enumerate(LEVELS)}
CORROBORATION_CAP = 10
# Only the student's own voice can bring back an entry they removed.
_RESTATING_SOURCES = ("user_explicit", "conversation")


@dataclass
class ItemWrite:
    outcome: VaultOutcome
    item: VaultItem | None
    issue_id: str | None = None
    reason: str | None = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive(moment: datetime | None) -> datetime | None:
    """SQLite hands back naive UTC; compare everything that way."""
    if moment is None:
        return None
    return moment.astimezone(timezone.utc).replace(tzinfo=None) if moment.tzinfo else moment


def _with_sighting(evidence: dict | None, source_type: str, level: str, incoming: dict,
                   candidate_id: str | None) -> dict:
    """Append one sighting (never the raw value) to corroborations, capped."""
    corr = list((evidence or {}).get("corroborations", []))
    sighting = {"source_type": source_type, "level": level, "quote": incoming.get("quote"),
                "source_language": incoming.get("source_language"),
                "observed_at": _now().isoformat(), "candidate_id": candidate_id}
    sighting.update({k: incoming[k] for k in ("file_id", "page") if k in incoming})
    corr.append(sighting)
    return {**(evidence or {}), "corroborations": corr[-CORROBORATION_CAP:]}


def _same(a, b) -> bool:
    if isinstance(a, str) and isinstance(b, str):
        return norm(a) == norm(b)
    return a == b


def _key(spec: TypeSpec, value: dict) -> tuple:
    return tuple(norm(str(value[f])) if value.get(f) is not None else None for f in spec.identity)


def _identity_match(spec: TypeSpec, new: tuple, old: tuple) -> bool:
    """Same entry? The first identity field must agree; later ones (a family
    member's name) only separate entries when both sides have them, so
    "brother Ali" and "brother Omar" stay two while "father" said twice is one."""
    if not spec.identity:
        return True  # singleton type
    if new[0] != old[0]:
        return False
    return all(n is None or o is None or n == o for n, o in zip(new[1:], old[1:]))


class VaultItemService:
    def __init__(self, db):
        self.db = db

    # ---- reads -------------------------------------------------------------

    def active(self, workspace_id: str, types: list[str] | None = None) -> list[VaultItem]:
        stmt = select(VaultItem).where(VaultItem.workspace_id == workspace_id, VaultItem.status == "active")
        if types:
            stmt = stmt.where(VaultItem.item_type.in_(list(types)))
        return list(self.db.scalars(stmt.order_by(VaultItem.created_at)))

    def history(self, workspace_id: str, item_id: str) -> list[VaultItem]:
        """Every row of this entry, oldest first: the superseded_by chain (which
        survives an edit that changed the identity) plus rows sharing its identity."""
        item = self._get(workspace_id, item_id)
        spec = self._spec(item.item_type)
        rows = self._rows(workspace_id, item.item_type)
        by_id = {r.id: r for r in rows}
        chain = {item.id}
        while True:
            later = {by_id[c].superseded_by for c in chain}
            grow = {r.id for r in rows if r.superseded_by in chain or r.id in later} - chain
            if not grow:
                break
            chain |= grow
        key = _key(spec, item.value)
        found = [r for r in rows if r.id in chain or _key(spec, r.value) == key]
        return sorted(found, key=lambda r: _naive(r.created_at))

    def was_retracted(self, workspace_id: str, item_type: str, value: dict) -> bool:
        spec = self._spec(item_type)
        key = _key(spec, value)
        rows = [r for r in self._rows(workspace_id, item_type) if _key(spec, r.value) == key]
        retracted = [_naive(r.valid_until) for r in rows if r.status == "retracted" and r.valid_until]
        if not retracted:
            return False
        since = max(retracted)
        for r in rows:
            if r.status == "retracted":
                continue
            if r.source_type in _RESTATING_SOURCES and _naive(r.created_at) > since:
                return False
            for c in (r.evidence or {}).get("corroborations", []):
                seen = c.get("observed_at")
                if c.get("source_type") in _RESTATING_SOURCES and seen and \
                        _naive(datetime.fromisoformat(seen)) > since:
                    return False
        return True

    # ---- writes ------------------------------------------------------------

    def apply(self, workspace_id: str, item_type: str, value: dict, *, source_type: str, level: str,
              confidence: float, evidence: dict | None, candidate_id: str | None, item_id: str | None = None,
              correction: bool = False, temporal: bool = False) -> ItemWrite:
        spec = self._spec(item_type)
        if level not in _RANK:
            raise MemoryDataError(f"Vault item {item_type!r}: unknown level {level!r}")
        try:
            validate_schema_instance(spec.schema, value)
        except SchemaValidationError as exc:
            raise MemoryDataError(f"Vault item {item_type!r} is invalid: {exc}") from exc
        self._lock(workspace_id)
        evidence = dict(evidence or {})

        current, loose = self._target(workspace_id, spec, value, item_id)
        if current is None:
            return ItemWrite(VaultOutcome.CREATED, self._insert(
                workspace_id, spec, value, source_type, level, confidence, evidence, candidate_id))
        old = current.value or {}

        # 1. Same meaning: one entry, more evidence.
        if all(k in old and _same(v, old[k]) for k, v in value.items()):
            current.evidence = _with_sighting(current.evidence, source_type, level, evidence, candidate_id)
            if _RANK[level] > _RANK[current.level]:
                current.level = level
                if level == "confirmed":
                    current.confirmed_at = _now()
            self.db.flush()
            return ItemWrite(VaultOutcome.CORROBORATED, current)

        # Step 4 also guards enrich: a guess neither replaces nor extends what
        # the student said or showed.
        guess = level == "inferred" and current.level != "inferred"

        # 1b. Enrich: only adds fields the entry lacks, contradicts none. The
        # existing row's fields (a name included) are kept as they are.
        if all(k not in old or _same(v, old[k]) for k, v in value.items()):
            if guess:
                return ItemWrite(VaultOutcome.RETAINED, current, reason="guess_against_stated")
            merged = {**old, **{k: v for k, v in value.items() if k not in old}}
            # The badge shows the weakest evidence behind any field, so it never
            # overstates; the document link survives via the carried file_id.
            top = min(_RANK[level], _RANK[current.level])
            # The old row's evidence (document reference included) stays on top;
            # the new evidence is kept as a sighting.
            carried = {**{k: v for k, v in evidence.items() if k != "corroborations"},
                       **{k: v for k, v in (current.evidence or {}).items() if k != "retraction"}}
            carried = _with_sighting(carried, source_type, level, evidence, candidate_id)
            # Adding detail answers nothing: an open question follows the entry.
            return self._supersede(current, spec, merged, source_type, LEVELS[top], confidence,
                                   carried, candidate_id, keep_cards=True)

        # A loose match (one side lacks a name) may only corroborate or enrich:
        # superseding here could erase a name or merge two people.
        if loose:
            if guess:
                return ItemWrite(VaultOutcome.RETAINED, current, reason="guess_against_stated")
            return self._ask_student(current, spec, value, candidate_id)

        # 2. The student's own edit always wins; a disagreeing document stays visible.
        # "Both true at different times" is a change over time, not a disagreement.
        if source_type == "user_explicit":
            if correction or temporal:
                evidence["change"] = "temporal" if temporal else "correction"
            if current.level == "shown" and not temporal:
                prior = current.evidence or {}
                evidence["disagreements"] = [*evidence.get("disagreements", []), {
                    "value": old, "source_type": current.source_type,
                    "file_id": prior.get("file_id"), "page": prior.get("page")}]
            return self._supersede(current, spec, value, source_type, level, confidence, evidence, candidate_id)

        # 4, checked before 3: a guess never replaces what the student said or
        # showed, whatever its change flags claim (same as facts and records).
        if guess:
            return ItemWrite(VaultOutcome.RETAINED, current, reason="guess_against_stated")

        # 3. The student's words say it is a correction or a change over time.
        if correction or temporal:
            evidence["change"] = "temporal" if temporal else "correction"
            return self._supersede(current, spec, value, source_type, level, confidence, evidence, candidate_id)

        # 5. Catalog rule.
        if spec.conflict == "latest_wins":
            return self._supersede(current, spec, value, source_type, level, confidence, evidence, candidate_id)
        if spec.conflict == "evidence_wins" and _RANK[level] > _RANK[current.level]:
            evidence["disagreements"] = [*evidence.get("disagreements", []), {
                "value": old, "source_type": current.source_type, "level": current.level}]
            return self._supersede(current, spec, value, source_type, level, confidence, evidence, candidate_id)
        return self._ask_student(current, spec, value, candidate_id)

    def retract(self, workspace_id: str, item_id: str, evidence: dict | None) -> VaultItem:
        self._lock(workspace_id)
        item = self._get(workspace_id, item_id, active=True)
        item.status, item.valid_until = "retracted", _now()
        item.evidence = {**(item.evidence or {}), "retraction": dict(evidence or {})}
        self._close_cards(item, "retracted")
        self.db.flush()
        return item

    def confirm(self, workspace_id: str, item_id: str) -> VaultItem:
        self._lock(workspace_id)
        item = self._get(workspace_id, item_id, active=True)
        item.level, item.confirmed_at, item.conflict_state = "confirmed", _now(), "none"
        self._close_cards(item, "confirmed")
        self.db.flush()
        return item

    # ---- internals ---------------------------------------------------------

    def _spec(self, item_type: str) -> TypeSpec:
        spec = vault_catalog().type(item_type)
        if spec is None or spec.storage != "item":
            raise MemoryDataError(f"{item_type!r} is not a Vault item type")
        return spec

    def _lock(self, workspace_id: str) -> None:
        """One write at a time per student."""
        if self.db.get(Workspace, workspace_id, with_for_update=True) is None:
            raise MemoryDataError("Student workspace does not exist")

    def _rows(self, workspace_id: str, item_type: str) -> list[VaultItem]:
        return list(self.db.scalars(select(VaultItem).where(
            VaultItem.workspace_id == workspace_id, VaultItem.item_type == item_type)))

    def _get(self, workspace_id: str, item_id: str, active: bool = False) -> VaultItem:
        item = self.db.get(VaultItem, item_id)
        if item is None or str(item.workspace_id) != str(workspace_id) or (active and item.status != "active"):
            raise MemoryDataError("Vault item does not exist or is no longer active")
        return item

    def _target(self, workspace_id: str, spec: TypeSpec, value: dict,
                item_id: str | None) -> tuple[VaultItem | None, bool]:
        """The active entry this value speaks about: the one named by an edit,
        else an exact identity match, else the single loose match."""
        if item_id:
            item = self._get(workspace_id, item_id, active=True)
            if item.item_type != spec.key:
                raise MemoryDataError(f"Vault item {item_id!r} is not a {spec.key!r}")
            return item, False
        key = _key(spec, value)
        live = self.active(workspace_id, [spec.key])
        exact = [r for r in live if _key(spec, r.value) == key]
        if exact:
            return exact[0], False
        loose = [r for r in live if _identity_match(spec, key, _key(spec, r.value))]
        return (loose[0], True) if len(loose) == 1 else (None, False)

    def _insert(self, workspace_id, spec, value, source_type, level, confidence, evidence, candidate_id):
        now = _now()
        item = VaultItem(workspace_id=workspace_id, item_type=spec.key, type_version=spec.version, value=value,
                         level=level, source_type=source_type, source_language=evidence.get("source_language"),
                         confidence=confidence, evidence=evidence, status="active", conflict_state="none",
                         observed_at=now, valid_from=now, created_at=now, candidate_id=candidate_id,
                         confirmed_at=now if level == "confirmed" else None)
        self.db.add(item)
        self.db.flush()
        return item

    def _supersede(self, current, spec, value, source_type, level, confidence, evidence, candidate_id,
                   keep_cards=False):
        new = self._insert(current.workspace_id, spec, value, source_type, level, confidence, evidence, candidate_id)
        current.status, current.superseded_by, current.valid_until = "superseded", new.id, new.valid_from
        if keep_cards:
            for issue in self._open_cards(current):
                issue.affected_id = new.id
                issue.evidence = {**(issue.evidence or {}), "current_value": new.value}
                new.conflict_state = "in_question"
        else:
            self._close_cards(current, "superseded")
        current.conflict_state = "none"
        self.db.flush()
        return ItemWrite(VaultOutcome.SUPERSEDED, new)

    def _open_cards(self, item: VaultItem) -> list[ProfileIssue]:
        return list(self.db.scalars(select(ProfileIssue).where(
            ProfileIssue.workspace_id == item.workspace_id, ProfileIssue.status == "open",
            ProfileIssue.affected_type == "vault_item", ProfileIssue.affected_id == item.id)
            .order_by(ProfileIssue.created_at)))

    def _close_cards(self, item: VaultItem, note: str) -> None:
        """A card about a row that is no longer the live, unsettled entry is obsolete."""
        for issue in self._open_cards(item):
            issue.status, issue.resolved_at = "resolved", _now()
            issue.resolution = {"action": "obsolete", "note": note, "resolved_by": "system",
                                "candidate_id": None}

    def _ask_student(self, current, spec, value, candidate_id) -> ItemWrite:
        """Stable facts are not overwritten silently: open one conflict card."""
        evidence = {"item_type": spec.key, "proposed_value": value, "current_value": current.value}
        cards = self._open_cards(current)
        if cards:
            # One question at a time: the open card now asks about the newest proposal.
            existing = cards[0]
            if (existing.evidence or {}).get("proposed_value") != value:
                earlier = list((existing.evidence or {}).get("earlier_candidate_ids", []))
                if candidate_id and existing.candidate_id and existing.candidate_id != candidate_id:
                    earlier.append(existing.candidate_id)
                if earlier:
                    evidence["earlier_candidate_ids"] = earlier
                existing.evidence = evidence
                existing.candidate_id = candidate_id or existing.candidate_id
            elif candidate_id and existing.candidate_id and existing.candidate_id != candidate_id:
                # The same proposal again: the card keeps asking about the first
                # one, and the repeat is listed so the caller can close it.
                earlier = list((existing.evidence or {}).get("earlier_candidate_ids", []))
                existing.evidence = {**existing.evidence, "earlier_candidate_ids": [*earlier, candidate_id]}
            current.conflict_state = "in_question"
            self.db.flush()
            return ItemWrite(VaultOutcome.NEEDS_REVIEW, None, issue_id=existing.id)
        label = spec.label.lower()
        issue = ProfileIssue(
            workspace_id=current.workspace_id, issue_type="conflict", conflict_kind="vault_item",
            severity="warning", affected_type="vault_item", affected_id=current.id, candidate_id=candidate_id,
            summary=f"A new {label} differs from the one already in the Vault.",
            clarification_question=f"Your {spec.label} is saved differently from what you just shared. "
                                   f"Which one is right?",
            evidence=evidence, status="open")
        self.db.add(issue)
        current.conflict_state = "in_question"
        self.db.flush()
        return ItemWrite(VaultOutcome.NEEDS_REVIEW, None, issue_id=issue.id)
