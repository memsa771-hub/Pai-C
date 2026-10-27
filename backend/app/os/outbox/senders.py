"""Email senders. Slice 1 ships LogSender only; a real provider is switched on before the pilot."""

import hashlib
import logging
from typing import TYPE_CHECKING, Protocol

import httpx
from sqlalchemy import Engine, insert

from app.os import models
from app.os.settings import OsSettings

if TYPE_CHECKING:
    from app.os.outbox.outbox import OutboxMessage

log = logging.getLogger("app.os.outbox")


class Sender(Protocol):
    def send(self, msg: "OutboxMessage") -> None: ...


class NotAllowed(Exception):
    """The recipient is not on the allow-list; nothing was sent. The outbox row becomes `blocked`."""


class Refused(Exception):
    """Resend answered 4xx; resending the same message will not help. The row becomes `failed`."""

    def __init__(self, status: int) -> None:
        super().__init__(f"email provider refused the message (HTTP {status})")
        self.status = status


def address_hash(recipient: str) -> str:
    """What logs show instead of an address."""
    return hashlib.sha256(recipient.strip().lower().encode()).hexdigest()


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


RESEND_URL = "https://api.resend.com/emails"


def _render(msg: "OutboxMessage") -> tuple[str, str]:
    """No template renderer exists yet: a minimal plain-text rendering of the template name and payload."""
    subject = msg.template.replace("_", " ").capitalize()
    lines = [f"{k}: {v}" for k, v in msg.payload.items()]
    return subject, "\n".join(lines) or subject


class ResendSender:
    """Sends through Resend to allow-listed addresses only. Network retries are the DBOS step's job (invariant 7)."""

    def __init__(self, settings: OsSettings, http: httpx.Client) -> None:
        self._key = settings.resend_api_key
        self._from = settings.email_from
        self._allow = settings.email_allowlist
        self._http = http

    def send(self, msg: "OutboxMessage") -> None:
        to = msg.recipient.strip().lower()
        digest = address_hash(to)
        if to not in self._allow:
            raise NotAllowed(digest)
        subject, text = _render(msg)
        log.info("email (resend) to_sha256=%s template=%s key=%s", digest, msg.template, msg.idempotency_key)
        resp = self._http.post(
            RESEND_URL, headers={"Authorization": f"Bearer {self._key}", "Idempotency-Key": msg.idempotency_key},
            json={"from": self._from, "to": [to], "subject": subject, "text": text})
        if 400 <= resp.status_code < 500:
            raise Refused(resp.status_code)
        resp.raise_for_status()  # 5xx (and anything else not 2xx) raises: the DBOS step retries


def make_sender(settings: OsSettings, engine: Engine | None) -> Sender:
    if settings.email_sender == "log":
        return LogSender(engine, settings.tenant_id)
    if settings.email_sender == "resend":
        return ResendSender(settings, httpx.Client(timeout=15.0))
    raise ValueError(f"email sender '{settings.email_sender}' is not available (use 'log' or 'resend')")
