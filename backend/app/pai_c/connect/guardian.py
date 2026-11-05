"""The guardian one-time e-mail link (R-10): a student under 18 needs a parent or guardian to agree before the
choice goes to the plan.

Tokens: `secrets.token_urlsafe(32)`; only the SHA-256 is stored; compared with `hmac.compare_digest`; an agree link
works 72 hours (consent_texts.yaml `links`), once. A link is bound to the decision version it was issued for: if that
is no longer the newest version, or the student's own consent is not set on it, the answer is `stale` and nothing is written but the audit row. A withdraw link has
no fixed lifetime: it works while the guardian consent it guards is live, and ends (`expired`) when a later consent
replaces it. A withdraw link that finds no live guardian consent answers `stale` without recording it, so it can
work again if that consent returns. Every other outcome sets `pai_guardian_consents.outcome`. The guardian's e-mail is personal data: it is masked in every log line and never
goes to PAI OS (DecisionRecordV2 has no field for it).

Nothing here commits; the caller's transaction carries the rows.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import GuardianConsent, RouteDecision
from app.pai_c.connect import consent
from app.pai_c.roadmap.decisions import RouteDecisionService
from app.security import rate_limit
from app.services import auth_emails
from app.services.email import mask_email

logger = logging.getLogger(__name__)

AGREE, WITHDRAW = "agree", "withdraw"


class GuardianRateLimited(Exception):
    """Too many requests (the router answers 429)."""


class GuardianRequestError(ValueError):
    """The decision cannot ask for a guardian's agreement (not this student's, not the newest, no guardian needed)."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _limit_ip(ip: str | None) -> None:
    if ip and not rate_limit.allow("guardian_open", ip=ip):
        raise GuardianRateLimited("guardian_open")


def _first_name(db, workspace_id: str) -> str:
    from app.pai_c.memory import MemoryService  # the Counsellor's one door to the Vault
    facts = MemoryService(db).profile(workspace_id).facts
    for key in ("identity.preferred_name", "identity.full_name"):
        value = (facts.get(key) or {}).get("value")
        if isinstance(value, str) and value.split():
            return value.split()[0]
    return consent.texts()["guardian_email"]["fallback_name"]


def _fill(block, **values):
    if isinstance(block, str):
        return block.format(**values)
    if isinstance(block, list):
        return [_fill(item, **values) for item in block]
    if isinstance(block, dict):
        return {key: _fill(item, **values) for key, item in block.items()}
    return block


def _issue(db, workspace_id: str, decision: RouteDecision, email: str, purpose: str,
           lifetime: timedelta | None) -> tuple[GuardianConsent, str]:
    token = secrets.token_urlsafe(32)
    row = GuardianConsent(workspace_id=workspace_id, decision_id=decision.id,
                          decision_version=decision.decision_version, purpose=purpose, email=email,
                          token_hash=_digest(token), expires_at=None if lifetime is None else now() + lifetime,
                          text_version=consent.current_version(), outcome="sent")
    db.add(row)
    db.flush()
    return row, token


def request(db, workspace_id: str, decision: RouteDecision, email: str) -> GuardianConsent:
    """E-mails the guardian a one-time link to agree to `decision`. Raises `GuardianRateLimited`."""
    consent.ensure_usable()
    email = email.strip().lower()
    newest = RouteDecisionService(db).newest(workspace_id)
    if decision.workspace_id != workspace_id or newest is None or newest.id != decision.id:
        raise GuardianRequestError("The decision is not this student's newest decision")
    if decision.status != "chosen" or not decision.guardian_required:
        raise GuardianRequestError("This decision needs no guardian agreement")
    if not rate_limit.allow("guardian_request", user=workspace_id, email=email):
        raise GuardianRateLimited("guardian_request")
    texts = consent.texts()
    row, token = _issue(db, workspace_id, decision, email, AGREE, timedelta(hours=texts["links"]["agree_hours"]))
    mail = _fill(texts["guardian_email"], student_first_name=_first_name(db, workspace_id),
                 hours=texts["links"]["agree_hours"])
    auth_emails.send_guardian_consent_email(
        email, auth_emails.guardian_link(token), subject=mail["subject"], title=mail["title"],
        paragraphs=mail["paragraphs"], button=mail["button"], footer=mail["footer"])
    logger.info("guardian: consent link sent to %s for decision version %s", mask_email(email),
                decision.decision_version)
    return row


def _lookup(db, token: str, purpose: str) -> GuardianConsent | None:
    digest = _digest(token or "")
    row = db.scalar(select(GuardianConsent).where(GuardianConsent.token_hash == digest))
    if row is None or not hmac.compare_digest(row.token_hash, digest) or row.purpose != purpose:
        return None
    return row


def workspace_of(db, token: str) -> str | None:
    """The workspace a link belongs to (for the caller's delivery after a change), or None for an unknown link."""
    row = db.scalar(select(GuardianConsent).where(GuardianConsent.token_hash == _digest(token or "")))
    return None if row is None else row.workspace_id


def purpose_of(db, token: str) -> str | None:
    """The kind of a link (agree or withdraw), or None for an unknown one. Reads nothing else."""
    return db.scalar(select(GuardianConsent.purpose).where(GuardianConsent.token_hash == _digest(token or "")))


def _stale(db, row: GuardianConsent) -> bool:
    newest = RouteDecisionService(db).newest(row.workspace_id)
    # An agree link works only while the student's own consent stands on the newest version.
    return (newest is None or newest.status != "chosen" or newest.decision_version != row.decision_version
            or newest.authorized_at is None)


def _withdraw_state(db, row: GuardianConsent) -> str:
    """ok | stale | expired for a withdraw link. It guards the guardian consent of the version it was issued for:
    live consent is ok; a different, later consent replaced it: expired; no live guardian consent now: stale."""
    guarded = db.scalar(select(RouteDecision.guardian_authorized_at).where(
        RouteDecision.workspace_id == row.workspace_id, RouteDecision.decision_version == row.decision_version))
    active = RouteDecisionService(db).active(row.workspace_id)
    live = None if active is None else active.guardian_authorized_at
    if live is None:
        return "stale"
    return "ok" if guarded is not None and _aware(live) == _aware(guarded) else "expired"


def _resolve(db, row: GuardianConsent) -> str:
    """ok | expired | used | stale. The first time an agree link turns expired or stale, the audit row says so; a
    withdraw link records only `expired` (stale is passing: the consent it guards may return)."""
    if row.outcome in ("agreed", "withdrawn"):
        return "used"
    if row.outcome in ("expired", "stale"):
        return row.outcome
    if row.purpose == WITHDRAW:
        state = _withdraw_state(db, row)
        if state == "expired":
            row.outcome = "expired"
            db.flush()
        return state
    if now() >= _aware(row.expires_at):
        row.outcome = "expired"
    elif _stale(db, row):
        row.outcome = "stale"
    else:
        return "ok"
    db.flush()
    return row.outcome


def _locked(db, token: str, purpose: str) -> tuple[GuardianConsent | None, str]:
    row = _lookup(db, token, purpose)
    if row is None:
        return None, "expired"  # an unknown link looks like an old one
    RouteDecisionService(db)._lock(row.workspace_id)
    db.refresh(row)
    return row, _resolve(db, row)


def open(db, token: str, *, ip: str | None = None, purpose: str | None = None) -> dict:  # noqa: A001 - the spec's name
    """What the link page shows: `{"state": "ok|expired|used|stale", "purpose", "text", "student_first_name"}`.
    With no `purpose` the token says which kind it is (one lookup, so one page load counts once). An unknown token is
    taken for an agree link. A withdraw link is neither gated by the text approval nor counted by the rate limit."""
    if purpose is None:
        purpose = purpose_of(db, token) or AGREE
    if purpose != WITHDRAW:  # withdrawing is never blocked by the text gate nor the rate limit
        consent.ensure_usable()
        _limit_ip(ip)
    row, state = _locked(db, token, purpose)
    if row is None or state != "ok":
        return {"state": state, "purpose": purpose, "text": None, "student_first_name": None}
    name = _first_name(db, row.workspace_id)
    key = "guardian_withdraw_page" if purpose == WITHDRAW else "guardian_page"
    return {"state": "ok", "purpose": purpose, "student_first_name": name,
            "text": _fill(consent.texts()[key], student_first_name=name)}


def agree(db, token: str, *, ip: str | None = None) -> str:
    """The guardian agrees: a new decision version carries `guardian_authorized_at`. Returns
    `agreed|expired|used|stale`; on `agreed` the guardian gets the confirmation e-mail with the withdraw link."""
    return agree_with_mail(db, token, ip=ip)[0]


def agree_with_mail(db, token: str, *, ip: str | None = None) -> tuple[str, bool]:
    """Like `agree`, and says whether the confirmation e-mail with the withdraw link was sent. A mail problem never
    undoes the agreement: it is logged (class name only) and reported as not sent; the student's resend then sends
    a fresh withdraw link (`resend_withdraw`)."""
    consent.ensure_usable()
    _limit_ip(ip)
    row, state = _locked(db, token, AGREE)
    if row is None or state != "ok":
        return state, False
    service = RouteDecisionService(db)
    moment = now()
    service.update_consent(row.workspace_id, guardian_authorized_at=moment)
    row.outcome, row.used_at = "agreed", moment
    _withdraw_row, withdraw_token = _issue(db, row.workspace_id, service.newest(row.workspace_id), row.email,
                                           WITHDRAW, None)
    sent = _send_withdraw_link(db, row.workspace_id, row.email, withdraw_token)
    logger.info("guardian: %s agreed for decision version %s", mask_email(row.email), row.decision_version)
    return "agreed", sent


def _send_withdraw_link(db, workspace_id: str, email: str, token: str) -> bool:
    """The confirmation e-mail with the withdraw link. A mail problem is logged (class name only), never raised."""
    mail = _fill(consent.texts()["guardian_confirmation"], student_first_name=_first_name(db, workspace_id))
    try:
        return bool(auth_emails.send_guardian_confirmation_email(
            email, auth_emails.guardian_link(token), subject=mail["subject"], title=mail["title"],
            paragraphs=mail["paragraphs"], button=mail["button"], footer=mail["footer"]))
    except Exception as exc:  # noqa: BLE001
        logger.warning("guardian: confirmation mail to %s failed (%s)", mask_email(email), type(exc).__name__)
        return False


def resend_withdraw(db, workspace_id: str) -> bool:
    """The guardian has agreed and may have lost (or never got) the withdraw link: a fresh withdraw link for the live
    agreement goes to the address on the agreed row, never to another one. Earlier withdraw links stay valid; the same
    rules apply (no fixed lifetime, ends when a later consent replaces the one it guards). Rate-limited like a
    request (`guardian_request`; raises `GuardianRateLimited`); never gated by the text approval, since it serves a
    withdrawal. Returns whether the e-mail went out."""
    service = RouteDecisionService(db)
    service._lock(workspace_id)
    active = service.active(workspace_id)
    if active is None or active.guardian_authorized_at is None:
        raise GuardianRequestError("Your guardian has not agreed")
    agreed = db.scalar(select(GuardianConsent).where(
        GuardianConsent.workspace_id == workspace_id, GuardianConsent.purpose == AGREE,
        GuardianConsent.outcome == "agreed").order_by(GuardianConsent.used_at.desc()).limit(1))
    if agreed is None:
        raise GuardianRequestError("No guardian agreement is on record")
    if not rate_limit.allow("guardian_request", user=workspace_id, email=agreed.email):
        raise GuardianRateLimited("guardian_request")
    _row, token = _issue(db, workspace_id, active, agreed.email, WITHDRAW, None)
    sent = _send_withdraw_link(db, workspace_id, agreed.email, token)
    logger.info("guardian: withdraw link sent again to %s for decision version %s", mask_email(agreed.email),
                active.decision_version)
    return sent


def withdraw(db, token: str, *, ip: str | None = None) -> str:
    """The guardian withdraws with the link of the confirmation e-mail: a new version clears
    `guardian_authorized_at`. Returns `withdrawn|expired|used|stale`. Never blocked by the text gate or counted by
    the rate limit (the token is 256 bits; a normal withdraw must never be turned away)."""
    row, state = _locked(db, token, WITHDRAW)
    if row is None or state != "ok":
        return state
    moment = now()
    RouteDecisionService(db).update_consent(row.workspace_id, guardian_authorized_at=None)
    row.outcome, row.used_at = "withdrawn", moment
    mail = _fill(consent.texts()["guardian_withdrawn"], student_first_name=_first_name(db, row.workspace_id))
    auth_emails.send_guardian_withdrawn_email(row.email, subject=mail["subject"], title=mail["title"],
                                              paragraphs=mail["paragraphs"], footer=mail["footer"])
    logger.info("guardian: %s withdrew at decision version %s", mask_email(row.email), row.decision_version)
    return "withdrawn"
