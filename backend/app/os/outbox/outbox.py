"""The outbox: every external send carries an idempotency key and is recorded first (invariant 8)."""

from dataclasses import dataclass

from sqlalchemy import Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from app.os import models
from app.os.outbox.senders import Sender

O = models.outbox


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
            new_id = conn.execute(insert(O).values(
                tenant_id=self.tenant_id, idempotency_key=key, channel=channel, recipient=recipient,
                template=template, payload=payload,
            ).on_conflict_do_nothing(constraint="uq_os_outbox_key").returning(O.c.id)).scalar_one_or_none()
        return new_id is not None

    def deliver(self, sender: Sender, limit: int = 100) -> int:
        """Sends pending messages one by one. A failed send leaves its row pending for the next run."""
        sent = 0
        for _ in range(limit):
            with self.engine.begin() as conn:
                row = conn.execute(select(O).where(O.c.tenant_id == self.tenant_id, O.c.status == "pending")
                                   .order_by(O.c.id).limit(1).with_for_update(skip_locked=True)).first()
                if row is None:
                    break
                sender.send(OutboxMessage(row.id, row.idempotency_key, row.channel, row.recipient, row.template,
                                          row.payload))
                conn.execute(update(O).where(O.c.id == row.id).values(
                    status="sent", sent_at=func.now(), attempts=O.c.attempts + 1))
                sent += 1
        return sent
