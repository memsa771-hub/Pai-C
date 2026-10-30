"""Email senders: LogSender (the default; rehearsals) and ResendSender (the pilot; Slices 9a and 9b)."""

import hashlib
import logging
import re
from typing import TYPE_CHECKING, Protocol

import httpx
from sqlalchemy import Engine, insert

from app.os import models
from app.os.outbox.templates import EmailTemplates, load_templates
from app.os.ports.recipients import RecipientLookup
from app.os.settings import OsSettings

if TYPE_CHECKING:
    from app.os.outbox.outbox import OutboxMessage

log = logging.getLogger("app.os.outbox")


class Sender(Protocol):
    def send(self, msg: "OutboxMessage") -> None: ...


class NotAllowed(Exception):
    """Nothing was sent and resending will not help: the outbox row becomes `blocked` with this reason.

    Reasons: `no_address` (the lookup found none), `invalid_address`, `not_on_allowlist`. `digest` is the address's
    SHA-256 when there is one; the address itself is never carried."""

    def __init__(self, reason: str, digest: str | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.digest = digest


class Refused(Exception):
    """Resend answered 4xx; resending the same message will not help. The row becomes `failed`."""

    def __init__(self, status: int) -> None:
        super().__init__(f"email provider refused the message (HTTP {status})")
        self.status = status


class ConfigError(Exception):
    """Resend answered 401, 403 or 422: our key, domain or From address is wrong, not this row. The outbox stops the
    pass, leaves every row `pending` and records one `email_config_error` event (Slice 9b). Carries only the code."""

    def __init__(self, status: int) -> None:
        super().__init__(f"email provider configuration error (HTTP {status})")
        self.status = status


class ProviderUnavailable(Exception):
    """Resend is unreachable, slow (408), rate-limiting (429) or failing (5xx): the DBOS step retries.

    Carries only a status code or an exception class name. httpx errors hold the request, whose headers hold the API
    key, and DBOS stores the errors of a step that ran out of retries; so no httpx exception may escape `send`.
    """


class RecipientLookupUnavailable(Exception):
    """The host's recipient lookup raised: treated as temporary, so the DBOS step retries and the row stays `pending`.
    Carries only the exception's class name: the original may hold an address, so it is never chained."""


RETRYABLE_4XX = (408, 429)
CONFIG_4XX = (401, 403, 422)  # Slice 9b: a wrong key, domain or From address; not the row
_ADDRESS = re.compile(r"[^@\s,;<>\"]+@[^@\s,;<>\"]+\.[^@\s,;<>\"]+")


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


class ResendSender:
    """Sends through Resend. Network retries are the DBOS step's job (invariant 7).

    Slice 9b: the outbox recipient is a student reference; the address comes from the host's RecipientLookup at send
    time and is checked against the allow-list. It is never stored or logged (only its SHA-256)."""

    def __init__(self, settings: OsSettings, http: httpx.Client, lookup: RecipientLookup,
                 templates: EmailTemplates | None = None) -> None:
        self._key = settings.resend_api_key
        self._from = settings.email_from
        self._allow = settings.email_allowlist
        self._app_url = settings.app_url
        self._http = http
        self._lookup = lookup
        self._templates = templates or load_templates()

    def _address(self, student_ref: str) -> str:
        failure = None
        try:
            found = self._lookup(student_ref)
        except Exception as e:  # noqa: BLE001  (any lookup failure is temporary: the step retries)
            failure = type(e).__name__
        if failure is not None:  # raised outside the except block: no __context__ that could hold an address
            raise RecipientLookupUnavailable(f"recipient lookup failed ({failure})")
        if not isinstance(found, str) or not found.strip():
            raise NotAllowed("no_address")
        return found.strip().lower()

    def send(self, msg: "OutboxMessage") -> None:
        to = self._address(msg.recipient)
        digest = address_hash(to)
        if not _ADDRESS.fullmatch(to):
            raise NotAllowed("invalid_address", digest)
        if to not in self._allow:
            raise NotAllowed("not_on_allowlist", digest)
        subject, text = self._templates.render(msg, self._app_url)
        log.info("email (resend) to_sha256=%s template=%s key=%s", digest, msg.template, msg.idempotency_key)
        failure = None
        try:
            resp = self._http.post(
                RESEND_URL, headers={"Authorization": f"Bearer {self._key}", "Idempotency-Key": msg.idempotency_key},
                json={"from": self._from, "to": [to], "subject": subject, "text": text})
        except httpx.HTTPError as e:
            failure = type(e).__name__
        if failure is not None:  # raised outside the except block, so there is no __context__ holding the request
            raise ProviderUnavailable(f"email provider unreachable ({failure})")
        code = resp.status_code
        if 200 <= code < 300:
            return
        if code in CONFIG_4XX:
            raise ConfigError(code)
        if 400 <= code < 500 and code not in RETRYABLE_4XX:
            raise Refused(code)
        raise ProviderUnavailable(f"email provider answered HTTP {code}")


def make_sender(settings: OsSettings, engine: Engine | None, lookup: RecipientLookup | None = None) -> Sender:
    """Templates are loaded (and checked) here, at worker start, whatever the sender."""
    templates = load_templates()
    if settings.email_sender == "log":
        return LogSender(engine, settings.tenant_id)
    if settings.email_sender == "resend":
        if lookup is None:
            raise ValueError("OS_EMAIL_SENDER=resend needs a recipient lookup (OS_RECIPIENT_LOOKUP on the worker)")
        return ResendSender(settings, httpx.Client(timeout=15.0), lookup, templates)
    raise ValueError(f"email sender '{settings.email_sender}' is not available (use 'log' or 'resend')")
