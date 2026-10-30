"""The admin email status (Slice 9b): which sender, whether a lookup is configured, rows per status, and the last
configuration error. Never an address, a key or the lookup's module path."""

from sqlalchemy import Engine, func, select

from app.os import models
from app.os.ports import recipients
from app.os.settings import OsSettings

STATUSES = ("pending", "sent", "skipped", "blocked", "failed")  # models.outbox's ck_os_outbox_status


def email_status(engine: Engine, settings: OsSettings) -> dict:
    O, E, tenant = models.outbox, models.events, settings.tenant_id
    with engine.connect() as conn:
        counts = dict(conn.execute(select(O.c.status, func.count())
                                   .where(O.c.tenant_id == tenant, O.c.channel == "email")
                                   .group_by(O.c.status)).all())
        last = conn.execute(select(E.c.at, E.c.payload).where(E.c.tenant_id == tenant, E.c.type == "email_config_error")
                            .order_by(E.c.id.desc()).limit(1)).first()
    return {
        "sender": settings.email_sender,
        "lookup_setting": settings.recipient_lookup is not None,  # OS_RECIPIENT_LOOKUP: what the worker loads
        "lookup_in_api": recipients.current() is not None,  # what the host passed to mount_os
        "allowlist_size": len(settings.email_allowlist),
        "app_url_set": settings.app_url is not None,
        "counts": {s: int(counts.get(s, 0)) for s in STATUSES},
        "last_config_error": None if last is None else {"at": last.at, "status": last.payload.get("status")},
    }
