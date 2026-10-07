# -*- coding: utf-8 -*-
"""Durable in-app notifications.

Notifications are stored in the workspace inbox and read through its API.
"""

from app.models import NotificationRecord
from sqlalchemy import select

REASON_APPROVAL = "approval"
REASON_TASK_COMPLETED = "task_completed"
REASON_ERROR = "error"


def notify(
    db,
    workspace_id: str,
    *,
    source: str,
    title: str,
    message: str,
    priority: str = "normal",
    channel_name: str | None = None,
    thread_id: str | None = None,
    link_url: str | None = None,
    dedupe_key: str | None = None,
    reason: str | None = None,
    push: bool = True,
) -> NotificationRecord:
    """Create and flush an inbox notification without committing.

    ``reason`` and ``push`` remain accepted temporarily so existing producers
    do not need a synchronized deployment; neither controls an external push
    transport anymore.
    """
    del reason, push
    record = NotificationRecord(
        workspace_id=str(workspace_id),
        created_by=source,
        title=title,
        message=message,
        priority=priority or "normal",
        channel_name=channel_name,
        thread_id=thread_id,
        link_url=link_url,
        dedupe_key=dedupe_key,
    )
    db.add(record)
    db.flush()
    return record


def notify_once(db, workspace_id: str, *, dedupe_key: str, **message) -> NotificationRecord:
    """Use one inbox event for an idempotent research lifecycle transition."""
    existing = db.execute(select(NotificationRecord).where(
        NotificationRecord.workspace_id == str(workspace_id),
        NotificationRecord.dedupe_key == dedupe_key)).scalar_one_or_none()
    return existing or notify(db, workspace_id, dedupe_key=dedupe_key, **message)
