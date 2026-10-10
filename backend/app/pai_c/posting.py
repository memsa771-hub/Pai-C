"""Shared event posting and bounded conversation transport helpers."""

import asyncio
import json as _json
import logging
from typing import Optional

from sqlalchemy import select

from app.config import config
from app.models import EventRecord

logger = logging.getLogger(__name__)


def _build_conversation_context(
    db, workspace_id: str, channel_target: str, agent_name: str,
    exclude_event_id: Optional[str] = None,
    before_timestamp: Optional[int] = None,
    max_chars: Optional[int] = None,
) -> list[dict]:
    """Fetch recent messages from the channel as conversation context.

    Only events causally prior to the trigger are eligible. When
    before_timestamp is given, rows at or after it are excluded in SQL, so
    a message committed after the trigger can never leak into this request
    and get answered early. Events carry no ordering finer than the unix-ms
    timestamp, so rows sharing the trigger's millisecond are conservatively
    dropped too. Without a boundary, the newest row is assumed to be the
    trigger and skipped (legacy behavior); exclude_event_id is a further
    guard for the id-only case.

    Chat messages are collected newest-first in pages until the window
    holds max_messages of them, the character budget is spent, or the scan
    cap is reached â€” non-chat rows (status/thinking/todos/anything else)
    never consume window slots. The character budget bounds prompt size for
    models with small context windows, which a message count alone does not.

    The scan cap makes this best-effort, deliberately: without it a busy
    channel would degrade into an unbounded table scan. If the most recent
    max_scanned rows are all noise, older chat history is invisible for
    this turn â€” a warning is logged when that happens.
    """
    max_messages = config.PAI_COUNSELOR_MAX_CONTEXT_MESSAGES
    if max_chars is None:
        max_chars = config.PAI_COUNSELOR_MAX_CONTEXT_CHARS

    batch_size = max(max_messages * 3, 100)
    max_scanned = batch_size * 10

    collected: list[dict] = []  # newest -> oldest
    used_chars = 0
    offset = 0
    drop_newest = exclude_event_id is None and before_timestamp is None

    while len(collected) < max_messages and offset < max_scanned:
        query = select(EventRecord).where(
            EventRecord.network_id == workspace_id,
            EventRecord.target == channel_target,
            EventRecord.type == "workspace.message.posted",
        )
        if before_timestamp is not None:
            query = query.where(EventRecord.timestamp < before_timestamp)

        rows = db.execute(
            query.order_by(EventRecord.timestamp.desc(), EventRecord.id.desc())
            .offset(offset)
            .limit(batch_size)
        ).scalars().all()
        if not rows:
            break

        done = False
        for row in rows:
            if drop_newest:
                drop_newest = False
                continue
            if exclude_event_id is not None and row.id == exclude_event_id:
                continue

            payload = row.payload or {}
            message_type = payload.get("message_type", "chat")
            if message_type not in {"chat", "counselor_mirror"} and not (
                message_type == "operator_result" and row.source == f"openagents:{agent_name}"
            ):
                continue
            content = payload.get("content", "")
            if not content:
                continue

            source = row.source or ""
            if source == f"openagents:{agent_name}":
                from app.pai_c.deep.polish import is_counselor_fallback
                if is_counselor_fallback(content):
                    continue
            if source == f"openagents:{agent_name}":
                role = "assistant"
            elif source.startswith("human:") or source.startswith("openagents:"):
                role = "user"
            else:
                continue

            if used_chars + len(content) > max_chars:
                # Keep at least a truncated newest message so the model
                # is never invoked with the trigger's context fully empty.
                if not collected and max_chars > 0:
                    collected.append({"role": role, "content": content[:max_chars]})
                done = True
                break

            collected.append({"role": role, "content": content})
            used_chars += len(content)
            if len(collected) >= max_messages:
                done = True
                break

        if done or len(rows) < batch_size:
            break
        offset += batch_size

    if len(collected) < max_messages and offset >= max_scanned:
        logger.warning(
            "counselor: context scan cap (%d rows) reached for %s in %s "
            "with only %d chat message(s) collected â€” older history, if any, "
            "is invisible this turn",
            max_scanned, agent_name, channel_target, len(collected),
        )

    collected.reverse()
    return collected


async def _post_response(
    db, workspace_id: str, channel_target: str, agent_name: str,
    content: str, depth: int,
    attachments: Optional[list] = None,
    message_type: str = "chat",
    metadata: Optional[dict] = None,
    extra_payload: Optional[dict] = None,
) -> Optional[str]:
    """Post the Counselor's response through the event pipeline.

    ``message_type``/``metadata`` let a caller other than an ordinary chat
    turn attribute its post distinctly â€” e.g. PAI Operator auto-posting a
    finished run's result uses ``message_type="operator_result"`` plus
    ``{"execution_run_id", "execution_status"}`` (see
    ``operator._post_result``) so the frontend can render it as an Operator
    execution result rather than an ordinary PAI Counselor reply, without
    this pipeline needing to know anything about Operator.

    Returns the persisted event id (None if the post was rejected), so callers
    that need to reference the committed turn â€” e.g. memory extraction â€” can
    do so without re-querying for it.
    """
    from app.models import Workspace
    from app.eventing.factory import pipeline
    from app.eventing.events import Event
    from app.eventing.mods import EventRejected, PipelineContext

    workspace = db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    ).scalar_one_or_none()

    if not workspace:
        logger.error("counselor: workspace %s not found", workspace_id)
        return None

    payload: dict = {
        **(extra_payload or {}),
        "content": content,
        "message_type": message_type,
    }
    if attachments:
        payload["attachments"] = attachments

    event = Event(
        type="workspace.message.posted",
        source=f"openagents:{agent_name}",
        target=channel_target,
        payload=payload,
        metadata={"counselor_depth": depth + 1, **(metadata or {})},
        visibility="channel",
        network=workspace_id,
    )

    context = PipelineContext(
        network_id=workspace_id,
        agent_address=event.source,
        db=db,
        workspace=workspace,
        token=workspace.password_hash,
    )

    try:
        await pipeline.process(event, context)
    except EventRejected as exc:
        logger.warning("counselor: response event rejected: %s", exc.reason)
        return None

    db.commit()

    snapshot = {
        "id": event.id,
        "type": event.type,
        "source": event.source,
        "target": event.target,
        "payload": event.payload,
        "metadata": event.metadata,
        "timestamp": event.timestamp,
    }

    # Publish to Redis so SSE clients receive the event in real-time
    try:
        from app.infrastructure import cache
        cache.publish_event(
            f"ws:{workspace_id}:events",
            _json.dumps(snapshot, default=str, separators=(",", ":")).encode(),
        )
    except Exception:
        pass

    # If this reply lands in a workflow thread, advance the run. Cloud replies
    # go through the pipeline directly (not the POST /v1/events route), so the
    # route's advance hook never sees them. advance_workflow is a no-op when the
    # channel has no active run; run it off the event loop so we don't block.
    try:
        from app.services.workflow import advance_workflow
        wf_event = {
            "target": event.target,
            "source": event.source,
            "payload": event.payload,
            "metadata": event.metadata,
        }
        asyncio.get_running_loop().run_in_executor(
            None, advance_workflow, workspace_id, wf_event,
        )
    except Exception:
        logger.warning("counselor: failed to schedule workflow advance", exc_info=True)

    # Cloud replies bypass POST /v1/events, so the route's Slack/Telegram
    # relay hook never sees them either â€” schedule it here the same way.
    try:
        from app.services.integrations import relay_for_event
        asyncio.get_running_loop().run_in_executor(
            None, relay_for_event, workspace_id, snapshot,
        )
    except Exception:
        logger.warning("counselor: failed to schedule integration relay", exc_info=True)

    # LAST. Every post-commit hook above must run before this returns â€”
    # returning early once orphaned the Redis publish, workflow advance and
    # integration relay, which cloud replies reach ONLY from here (they bypass
    # the POST /v1/events route that schedules them for everyone else).
    return event.id


async def send_to_student(
    db, workspace_id: str, channel_target: str, agent_name: str,
    content: str, depth: int,
    attachments: Optional[list] = None,
    message_type: str = "chat",
    metadata: Optional[dict] = None,
    extra_payload: Optional[dict] = None,
) -> Optional[str]:
    """The public Messenger path; keep every existing delivery hook unchanged."""
    return await _post_response(
        db, workspace_id, channel_target, agent_name, content, depth,
        attachments=attachments, message_type=message_type,
        metadata=metadata, extra_payload=extra_payload)
