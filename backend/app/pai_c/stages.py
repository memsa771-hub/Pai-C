"""Server-owned state machine for the Counselor phase of a Journey."""

import logging

logger = logging.getLogger(__name__)

IDENTITY = "IDENTITY"
FOUNDATION = "FOUNDATION"
DIRECTION = "DIRECTION"
MIRROR = "MIRROR"
RESEARCHING = "RESEARCHING"
ASSESSING = "ASSESSING"
NEEDS_INFO = "NEEDS_INFO"
PROPOSED = "PROPOSED"
CHOSEN = "CHOSEN"

# The journey follows the Vault (FOUR_FEATURES_SPEC 2.4): DIRECTION -> MIRROR
# when the Mirror state card is ready (the reconciler, after the write that made
# it ready), MIRROR -> PROPOSED when the Path engine saves the first paths.
# RESEARCHING, ASSESSING and NEEDS_INFO were the confirm-gated research wait; no
# code enters them any more (migration 121 moved the journeys left there), but
# the names stay for old data and a journey still there may move on to PROPOSED.
# Withdrawing a chosen route goes back to PROPOSED; a rethink goes to DIRECTION.
TRANSITIONS = {
    IDENTITY: frozenset({FOUNDATION}),
    FOUNDATION: frozenset({DIRECTION}),
    DIRECTION: frozenset({MIRROR}),
    MIRROR: frozenset({PROPOSED}),
    RESEARCHING: frozenset({PROPOSED}),
    ASSESSING: frozenset({PROPOSED}),
    NEEDS_INFO: frozenset({PROPOSED}),
    PROPOSED: frozenset({DIRECTION, CHOSEN}),
    CHOSEN: frozenset({DIRECTION, PROPOSED}),
}


def require_counselor_transition(current: str, target: str, *,
                                 validated_choice: bool = False,
                                 replan_escalation: bool = False) -> str:
    if current not in TRANSITIONS or target not in TRANSITIONS:
        logger.warning("counselor stage rejected unknown stage %s -> %s", current, target)
        raise ValueError("Unknown Counselor stage")
    if target == current:
        return current
    if (target not in TRANSITIONS[current] or (target == CHOSEN and not validated_choice)
            or (current == CHOSEN and target == DIRECTION and not replan_escalation)):
        logger.warning("counselor stage rejected %s -> %s", current, target)
        raise ValueError(f"Invalid Counselor transition: {current} -> {target}")
    return target


def advance_discovery_stage(journeys, workspace_id: str, journey, *,
                            identity_ready: bool, foundation_ready: bool,
                            goal_records: list[dict], actor: str = "system"):
    """Advance only when accepted student data satisfies the next gate."""
    if journey.current_stage == IDENTITY and identity_ready:
        journey = journeys.set_counselor_stage(
            workspace_id, journey.id, FOUNDATION, actor=actor)
    if journey.current_stage == FOUNDATION and foundation_ready:
        journey = journeys.set_counselor_stage(
            workspace_id, journey.id, DIRECTION, actor=actor)
    return journey
