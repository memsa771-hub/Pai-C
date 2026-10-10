# -*- coding: utf-8 -*-
"""Enqueue memory extraction after a PAI Counselor turn has persisted.

The one place that decides "this turn is worth extracting from". Called from
`counseling.runtime._run_turn` AFTER its reply commits, so nothing here
is on the chat-response critical path.

Why that call site and not `POST /v1/events`: PAI Counselor's reply never goes
through that handler. It is produced in a background task and written straight
to the pipeline by `counseling.runtime._post_response`, so a hook on the HTTP route
would see the student's message but never the reply, and could not know when a
*turn* was complete. The assistant path is also the only place that knows the
reply came from the tool-using assistant rather than an image/audio/error path.

Scoped to PAI Counselor deliberately: only the student's counselor forms this
kind of long-term memory.
"""

import logging
from typing import Optional

from app.runtime.task_runtime import enqueue
from app.memory.handlers import JOB_EXTRACT

logger = logging.getLogger(__name__)


def enqueue_turn_extraction(
    db,
    workspace_id: str,
    channel_target: str,
    user_event_id: Optional[str],
    assistant_event_id: Optional[str],
    agent_name: str,
    profile_captured: bool = False,
) -> Optional[str]:
    """Queue extraction for one completed turn. Returns the job id, or None.

    Caller must have COMMITTED the assistant reply first — the payload carries
    only IDs, and the worker reads those rows back from PostgreSQL.

    Idempotent on the student event: a retry or duplicated reply cannot queue
    a second extraction of the same student statement.

    Never raises. Memory formation is an enhancement to a conversation that has
    already succeeded; a failure here must not surface to the student.
    """
    if not user_event_id:
        # Nothing to attribute student truth to. Extraction without a user
        # event could only mine the assistant's own words, which requirement 7
        # forbids from becoming student facts.
        logger.debug("memory: skipping turn with no user event (workspace=%s)", workspace_id)
        return None

    try:
        job = enqueue(db,
            job_type=JOB_EXTRACT,
            workspace_id=workspace_id,
            payload={
                "source_type": "conversation",
                "channel": channel_target,
                "user_event_id": user_event_id,
                "assistant_event_id": assistant_event_id,
                "agent_name": agent_name,
                "profile_captured": profile_captured,
            },
            idempotency_key=f"extract:turn:{user_event_id}",
        )
        db.commit()
        logger.info(
            "memory: queued extraction job=%s workspace=%s user_event=%s assistant_event=%s",
            job.id, workspace_id, user_event_id, assistant_event_id,
        )
        return job.id
    except Exception:
        db.rollback()
        logger.exception(
            "memory: failed to queue extraction workspace=%s user_event=%s",
            workspace_id, user_event_id,
        )
        return None
