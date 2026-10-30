"""The outbox: every external send carries an idempotency key and is recorded first (invariant 8)."""

import logging
from dataclasses import dataclass

from sqlalchemy import Engine, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.os import models
from app.os.outbox.senders import ConfigError, NotAllowed, Refused, Sender
from app.os.outbox.templates import Unrenderable

log = logging.getLogger("app.os.outbox")
O = models.outbox
GLUE_CHANNELS = ("counsellor",)  # delivered by the host's glue (Slice 8), never by a sender here


@dataclass(frozen=True)
class OutboxMessage:
    id: int
    idempotency_key: str
    channel: str
    recipient: str
    template: str
    payload: dict


class Outbox:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    def add(self, key: str, channel: str, recipient: str, template: str, payload: dict) -> bool:
        """False when a message with this key already exists (so a re-run never sends twice)."""
        with self.engine.begin() as conn:
            new_id = conn.execute(pg_insert(O).values(
                tenant_id=self.tenant_id, idempotency_key=key, channel=channel, recipient=recipient,
                template=template, payload=payload,
            ).on_conflict_do_nothing(constraint="uq_os_outbox_key").returning(O.c.id)).scalar_one_or_none()
        return new_id is not None

    def _event(self, conn, type_: str, payload: dict) -> None:
        """A tenant-wide email event (plan_id null). Never an address: at most its SHA-256."""
        conn.execute(insert(models.events).values(tenant_id=self.tenant_id, type=type_, payload=payload))

    def deliver(self, sender: Sender, limit: int = 100) -> int:
        """Sends pending messages one by one. A failed send leaves its row pending for the next run.

        Slice 9b: `blocked` (no address, invalid address, not on the allow-list) and `failed` (refused, unrenderable)
        rows get an `email_blocked` / `email_failed` event with the reason. A provider configuration error (401, 403,
        422) stops the pass with every row left pending, and records one `email_config_error` event, logged at ERROR.
        A lookup or provider outage raises, so the DBOS step retries (invariant 7)."""
        sent = 0
        for _ in range(limit):
            with self.engine.begin() as conn:
                row = conn.execute(select(O).where(O.c.tenant_id == self.tenant_id, O.c.status == "pending",
                                                   O.c.channel.not_in(GLUE_CHANNELS))
                                   .order_by(O.c.id).limit(1).with_for_update(skip_locked=True)).first()
                if row is None:
                    break
                info = {"idempotency_key": row.idempotency_key, "template": row.template}
                try:
                    sender.send(OutboxMessage(row.id, row.idempotency_key, row.channel, row.recipient, row.template,
                                              row.payload))
                except ConfigError as e:  # our settings are wrong, not this row: stop, keep everything pending
                    log.error("email configuration error: the provider answered HTTP %s; delivery stopped, every "
                              "row stays pending until the settings are fixed (see GET /v1/os/admin/email-status)",
                              e.status)
                    self._event(conn, "email_config_error", {"status": e.status})
                    break
                except NotAllowed as e:
                    log.warning("email blocked (%s) to_sha256=%s key=%s", e.reason, e.digest or "-",
                                row.idempotency_key)
                    self._event(conn, "email_blocked", {**info, "reason": e.reason,
                                                        **({"to_sha256": e.digest} if e.digest else {})})
                    conn.execute(update(O).where(O.c.id == row.id).values(status="blocked",
                                                                         attempts=O.c.attempts + 1))
                    continue
                except (Refused, Unrenderable) as e:  # terminal: the row leaves pending; go on to the next row
                    detail = ({"reason": "refused", "status": e.status} if isinstance(e, Refused)
                              else {"reason": "unrenderable", "detail": str(e)[:200]})
                    log.warning("email failed (%s) key=%s", detail.get("status") or detail["detail"],
                                row.idempotency_key)
                    self._event(conn, "email_failed", {**info, **detail})
                    conn.execute(update(O).where(O.c.id == row.id).values(status="failed", attempts=O.c.attempts + 1))
                    continue
                conn.execute(update(O).where(O.c.id == row.id).values(
                    status="sent", sent_at=func.now(), attempts=O.c.attempts + 1))
                sent += 1
        return sent
