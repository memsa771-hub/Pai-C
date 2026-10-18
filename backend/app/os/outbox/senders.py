"""Email senders. Slice 1 ships LogSender only; a real provider is switched on before the pilot."""

import logging
from typing import TYPE_CHECKING, Protocol

from sqlalchemy import Engine, insert

from app.os import models
from app.os.settings import OsSettings

if TYPE_CHECKING:
    from app.os.outbox.outbox import OutboxMessage

log = logging.getLogger("app.os.outbox")


class Sender(Protocol):
    def send(self, msg: "OutboxMessage") -> None: ...


class LogSender:
    """Logs the message and records an `email_logged` event; nothing leaves the system."""

    def __init__(self, engine: Engine | None, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    def send(self, msg: "OutboxMessage") -> None:
        log.info("email (logged, not sent) to=%s template=%s key=%s", msg.recipient, msg.template,
                 msg.idempotency_key)
        if self.engine is not None:
            with self.engine.begin() as conn:
                conn.execute(insert(models.events).values(
                    tenant_id=self.tenant_id, type="email_logged",
                    payload={"recipient": msg.recipient, "template": msg.template,
                             "idempotency_key": msg.idempotency_key, "payload": msg.payload}))


def make_sender(settings: OsSettings, engine: Engine | None) -> Sender:
    if settings.email_sender == "log":
        return LogSender(engine, settings.tenant_id)
    raise ValueError(f"email sender '{settings.email_sender}' is not available in Slice 1 (use 'log')")
