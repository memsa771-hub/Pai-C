"""The guardian one-time e-mail link (R-10): a student under 18 needs a parent or guardian to agree before the
choice goes to the plan.

Tokens: `secrets.token_urlsafe(32)`; only the SHA-256 is stored; compared with `hmac.compare_digest`; an agree link
works 72 hours (consent_texts.yaml `links`), once. A link is bound to the decision version it was issued for: if that
is no longer the newest version the answer is `stale` and nothing is written but the audit row. A withdraw link has
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
    from app.memory.student_snapshot import StudentSnapshotService
    facts = StudentSnapshotService(db).build(workspace_id).facts
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


def _stale(db, row: GuardianConsent) -> bool:
    newest = RouteDecisionService(db).newest(row.workspace_id)
    return newest is None or newest.status != "chosen" or newest.decision_version != row.decision_version


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


def open(db, token: str, *, ip: str | None = None, purpose: str = AGREE) -> dict:  # noqa: A001 - the spec's name
    """What the link page shows: `{"state": "ok|expired|used|stale", "text", "student_first_name"}`."""
    consent.ensure_usable()
    _limit_ip(ip)
    row, state = _locked(db, token, purpose)
    if row is None or state != "ok":
        return {"state": state, "text": None, "student_first_name": None}
    name = _first_name(db, row.workspace_id)
    return {"state": "ok", "student_first_name": name,
            "text": _fill(consent.texts()["guardian_page"], student_first_name=name)}


def agree(db, token: str, *, ip: str | None = None) -> str:
    """The guardian agrees: a new decision version carries `guardian_authorized_at`. Returns
    `agreed|expired|used|stale`; on `agreed` the guardian gets the confirmation e-mail with the withdraw link."""
    consent.ensure_usable()
    _limit_ip(ip)
    row, state = _locked(db, token, AGREE)
    if row is None or state != "ok":
        return state
    service = RouteDecisionService(db)
    moment = now()
    service.update_consent(row.workspace_id, guardian_authorized_at=moment)
    row.outcome, row.used_at = "agreed", moment
    texts = consent.texts()
    withdraw_row, withdraw_token = _issue(db, row.workspace_id, service.newest(row.workspace_id), row.email,
                                          WITHDRAW, None)
    mail = _fill(texts["guardian_confirmation"], student_first_name=_first_name(db, row.workspace_id))
    auth_emails.send_guardian_confirmation_email(
        row.email, auth_emails.guardian_link(withdraw_token), subject=mail["subject"], title=mail["title"],
        paragraphs=mail["paragraphs"], button=mail["button"], footer=mail["footer"])
    logger.info("guardian: %s agreed for decision version %s", mask_email(row.email), row.decision_version)
    return "agreed"


def withdraw(db, token: str, *, ip: str | None = None) -> str:
    """The guardian withdraws with the link of the confirmation e-mail: a new version clears
    `guardian_authorized_at`. Returns `withdrawn|expired|used|stale`. Never blocked by the text gate."""
    _limit_ip(ip)
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
