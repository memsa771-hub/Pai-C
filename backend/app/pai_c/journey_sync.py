"""The one place the counselor journey moves on by itself (FOUR_FEATURES_SPEC 2.4).

Several writers can change what the stage should be: a Vault write (the
reconciler's Mirror hook), the analyst's notebook write (its turn advances
DIRECTION), a path analysis that saved paths, and a route choice. Each calls
`sync_counselor_stage`, so the rules live here once:

- DIRECTION -> MIRROR when the Mirror state card is ready and the journey has
  never passed the Mirror (`mirror_ready_at`, the first not-ready -> ready edge);
- MIRROR (or the old research wait) -> PROPOSED when a live path exists;
- PROPOSED -> CHOSEN when a route decision is active (`follow_active`).

Re-plan guard: a rethink or a PAI OS escalation moves the journey back to
DIRECTION and records `replan_at` (JourneyService.set_counselor_stage). While it
is set nothing here moves the stage, whatever the Vault, the Mirror or a quiet
path run says; otherwise the student's next fact would undo the re-plan. Only
the student's own act ends it: choosing a route (reason "chosen") or asking
for paths and getting them (reason "asked"). The journey then goes through
MIRROR to PROPOSED (and CHOSEN with an active route); it passed the Mirror
before, so its readiness is not asked again.

The caller commits.
"""

import logging

from sqlalchemy import select

from app.journey import JourneyService
from app.models import StudentJourney
from app.pai_c.stages import DIRECTION, MIRROR, PROPOSED

logger = logging.getLogger(__name__)

# Reasons that are the student's own act and so end a re-plan.
REPLAN_ENDERS = frozenset({"asked", "chosen"})
# The old confirm-gated research wait, kept for old data (stages.py).
_OLD_WAIT = frozenset({"RESEARCHING", "ASSESSING", "NEEDS_INFO"})


def _journey(db, workspace_id: str) -> StudentJourney | None:
    return db.scalar(select(StudentJourney).where(
        StudentJourney.workspace_id == workspace_id, StudentJourney.journey_type == "counselor_decision",
        StudentJourney.status == "active").limit(1))


def _live_paths(db, workspace_id: str) -> bool:
    from app.pai_c.possibilities import PossibilityService
    return any(row.status != "dismissed" for row in PossibilityService(db).list(workspace_id))


def _propose(db, journey: StudentJourney, actor: str) -> None:
    """MIRROR -> PROPOSED, then an active route decision takes it to CHOSEN."""
    from app.pai_c.roadmap.decisions import RouteDecisionService
    if journey.current_stage != PROPOSED:
        JourneyService(db).set_counselor_stage(journey.workspace_id, journey.id, PROPOSED, actor=actor)
    RouteDecisionService(db).follow_active(journey.workspace_id, actor=actor)


def sync_counselor_stage(db, workspace_id: str, *, reason: str, actor: str | None = None) -> str | None:
    """Move the journey as far as the Vault, the paths and the route decision
    allow, and return the stage. `reason` names the writer ("vault",
    "analyst", a path run's reason, "chosen")."""
    journey = _journey(db, workspace_id)
    if journey is None:
        return None
    actor = actor or f"system:stage_sync:{reason}"
    replanning = journey.replan_at is not None
    if replanning and reason not in REPLAN_ENDERS:
        return journey.current_stage
    if journey.current_stage == DIRECTION:
        if replanning:
            if not _live_paths(db, workspace_id):
                return journey.current_stage
        else:
            from app.pai_c.mirror import MirrorEngine
            if journey.mirror_ready_at is not None or not MirrorEngine(db).ready(workspace_id):
                return journey.current_stage
        JourneyService(db).set_counselor_stage(workspace_id, journey.id, MIRROR, actor=actor)
    if journey.current_stage in {MIRROR, PROPOSED, *_OLD_WAIT} and _live_paths(db, workspace_id):
        try:
            # Its own savepoint: a failed move on keeps MIRROR.
            with db.begin_nested():
                _propose(db, journey, actor)
        except Exception as exc:  # noqa: BLE001  the earlier move and the caller's writes stand
            logger.error("stage_sync_propose_failed workspace_id=%s reason=%s error_type=%s",
                         workspace_id, reason, type(exc).__name__)
    return journey.current_stage
