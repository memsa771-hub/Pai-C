# -*- coding: utf-8 -*-
"""
Human identity and workspace access for Placement AI.

One student, one personal workspace. There is no second human in a workspace,
so there is no role hierarchy, no invitations, no collaborators, and nothing to
reconcile. Authorization is two rules:

  1. Machine token — `X-Workspace-Token` == `workspace.password_hash`.
     The credential agents and daemons use (PAI Counselor/Operator reach the
     workspace API with it). Fully trusted.
  2. Owner identity — a verified bearer whose `User.id` equals
     `workspace.owner_user_id`.

Anything else is denied, including an anonymous caller and a logged-in user
who simply is not the owner. `workspaces.owner_user_id` is the tenant-isolation
boundary, and `uq_workspace_owner_active` (partial unique index) is what makes
"exactly one active personal workspace per user" a database guarantee rather
than a convention.

Human identity comes ONLY from the verified authentication token. Nothing in
an event payload or request body — `sender_email`, `role`, `owner` — is ever
read as an identity claim; a client could set any of them.
"""

import hashlib
import logging
import re
import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm import Session as SqlaSession

from app.security.human_auth import verify_identity_claims
from app.models import AuthIdentity, User, Workspace

logger = logging.getLogger(__name__)


class AuthAccountConflict(Exception):
    """A verified provider subject conflicts with an existing PAI account."""


def _available_username(db: Session, claims: dict, email: str) -> str:
    """Choose a login handle without adding another onboarding screen."""
    requested = (claims.get("username") or "").strip().lower()
    if re.fullmatch(r"[a-z0-9_-]{3,32}", requested):
        taken = db.execute(
            select(User.id).where(User.username.isnot(None), User.username.ilike(requested))
        ).first()
        if taken is None:
            return requested

    local_part = email.split("@", 1)[0].lower()
    base = re.sub(r"[^a-z0-9_-]+", "_", local_part).strip("_-") or "user"
    if len(base) < 3:
        base = f"user_{base}"
    identity = claims.get("subject") or claims.get("supabase_uid") or email
    suffix = hashlib.sha256(str(identity).encode("utf-8")).hexdigest()[:10]
    return f"{base[:21]}_{suffix}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def extract_bearer(authorization: Optional[str]) -> Optional[str]:
    """Extract the token from an `Authorization: Bearer <id>` header."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return None


# ---------------------------------------------------------------------------
# User resolution
# ---------------------------------------------------------------------------

def get_or_create_user(db: Session, claims: dict) -> Optional[User]:
    """Resolve by stable provider subject, preserving legacy account IDs."""
    if claims.get("session_user_id"):
        return db.get(User, claims["session_user_id"])
    email = (claims.get("email") or "").strip().lower()
    provider = str(claims.get("provider") or "supabase")
    subject = str(claims.get("subject") or claims.get("supabase_uid") or "")
    supabase_subject = subject if provider == "supabase" else None
    if not email or not subject:
        return None

    identity = db.execute(select(AuthIdentity).where(
        AuthIdentity.provider == provider,
        AuthIdentity.provider_subject == subject,
    )).scalar_one_or_none()
    user = db.get(User, identity.user_id) if identity else None
    if user is None and supabase_subject:
        user = db.execute(select(User).where(User.supabase_uid == subject)).scalar_one_or_none()
    if user is None:
        legacy = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if legacy and (not supabase_subject or legacy.supabase_uid not in (None, "", subject)):
            raise AuthAccountConflict("Email belongs to another identity")
        user = legacy
    if user is None:
        try:
            with db.begin_nested():
                user = User(
                    email=email, supabase_uid=supabase_subject,
                    username=_available_username(db, claims, email),
                    display_name=claims.get("display_name"),
                    last_login_at=_now(),
                )
                db.add(user)
                db.flush()
        except IntegrityError:
            user = (db.execute(select(User).where(User.supabase_uid == subject)).scalar_one_or_none()
                    if supabase_subject else None)
            if user is None:
                raise AuthAccountConflict("Account creation conflict")
    if not identity:
        try:
            with db.begin_nested():
                db.add(AuthIdentity(
                    user_id=user.id, provider=provider,
                    provider_subject=subject, email=email))
                db.flush()
        except IntegrityError:
            existing = db.execute(select(AuthIdentity).where(
                AuthIdentity.provider == provider,
                AuthIdentity.provider_subject == subject,
            )).scalar_one_or_none()
            if not existing or str(existing.user_id) != str(user.id):
                raise AuthAccountConflict("Identity is linked to another account")
    else:
        identity.email = email
        identity.updated_at = _now()
    if user.email != email:
        other = db.execute(select(User.id).where(User.email == email, User.id != user.id)).first()
        if other:
            raise AuthAccountConflict("Email belongs to another account")
        user.email = email
    if supabase_subject and not user.supabase_uid:
        user.supabase_uid = subject
    if claims.get("display_name") and not user.display_name:
        user.display_name = claims["display_name"]
    if not user.username:
        user.username = _available_username(db, claims, email)
    user.last_login_at = _now()
    return user


def resolve_current_user(db: Session, authorization: Optional[str]) -> Optional[User]:
    """Verify a PAI session and return its account, or None."""
    bearer = extract_bearer(authorization)
    if not bearer:
        return None
    claims = verify_identity_claims(bearer)
    if not claims:
        return None
    return get_or_create_user(db, claims)


# ---------------------------------------------------------------------------
# The one personal workspace
# ---------------------------------------------------------------------------

def provision_workspace(db: Session, user: User, name: str = "My Workspace") -> Workspace:
    """Create the student's personal workspace, owned by `user`.

    Keeps a workspace token: that is the machine credential PAI's agents use.
    Does NOT commit — the caller owns the transaction.
    """
    ws = Workspace(
        slug=secrets.token_hex(4),
        name=name,
        owner_user_id=user.id,
        password_hash=secrets.token_urlsafe(32),
        require_login=True,
        settings={},
        status="active",
    )
    db.add(ws)
    db.flush()

    # A first workspace with no agent is a dead end, especially on mobile where
    # the launcher cannot be installed. Never let this block creation.
    try:
        from app.services.pai import provision_pai, seed_welcome_thread
        if provision_pai(db, ws):
            seed_welcome_thread(db, ws)
    except Exception:
        logger.warning("provision_workspace: failed to provision PAI Counselor", exc_info=True)
    return ws


def resolve_owned_workspace(db: Session, user: User) -> Optional[Workspace]:
    """The student's one personal workspace, or None if not yet provisioned."""
    return db.execute(
        select(Workspace).where(
            Workspace.owner_user_id == user.id,
            Workspace.status == "active",
        )
    ).scalar_one_or_none()


def get_or_create_owned_workspace(db: Session, user: User) -> Workspace:
    """The student's one personal workspace, provisioning it on first call.

    Idempotent and concurrency-safe: `uq_workspace_owner_active` is the actual
    guarantee, enforced by the database, so two concurrent first-logins (two
    tabs, web + desktop) can never both insert an owned workspace for the same
    user. The loser of that race re-reads the winner's row.

    Does NOT commit. Safe inside an existing transaction: the insert runs in its
    own SAVEPOINT so a conflict rolls back only the failed insert.
    """
    existing = resolve_owned_workspace(db, user)
    if existing is not None:
        return existing

    try:
        with db.begin_nested():
            ws = provision_workspace(db, user)
            db.flush()
    except IntegrityError:
        logger.info(
            "get_or_create_owned_workspace: lost a concurrent-provisioning race "
            "for user %s — re-reading the winner's workspace", user.id,
        )
        ws = resolve_owned_workspace(db, user)
        if ws is None:
            # Only possible if the conflict wasn't the ownership index (e.g. a
            # transient DB error) — surface it rather than loop.
            raise
    return ws


# ---------------------------------------------------------------------------
# Access verification
# ---------------------------------------------------------------------------

def resolve_machine_token(db: Session, token: str):
    """Map a machine token to (workspace, node) — the single source of truth.

    Used by BOTH the access check and /v1/token/resolve so the two can never
    disagree about what a token means. `node` is always None now that per-node
    tokens are gone; the tuple shape is kept for the callers that unpack it.
    """
    if not token:
        return None, None
    ws = db.execute(
        select(Workspace).where(
            Workspace.password_hash == token,
            Workspace.status != "deleted",
        )
    ).scalar_one_or_none()
    if ws is not None:
        return ws, None
    return None, None


def is_workspace_owner(db: Session, workspace: Workspace, authorization: Optional[str]) -> bool:
    """True if the verified bearer belongs to this workspace's owner.

    The identity is taken from the token's claims and matched against
    `workspace.owner_user_id`. A workspace with no owner has no human who can
    reach it — only its machine token.
    """
    if workspace.owner_user_id is None:
        return False
    bearer = extract_bearer(authorization)
    if not bearer:
        return False
    claims = verify_identity_claims(bearer)
    if not claims:
        return False
    return str(workspace.owner_user_id) == str(claims.get("session_user_id"))


def verify_workspace_access(
    workspace: Workspace,
    token: Optional[str],
    authorization: Optional[str],
    db: Optional[Session] = None,
) -> bool:
    """The single access check: machine token, or the owner. Nothing else.

    `db` is optional — when omitted it is derived from the workspace's own
    session, so the thin router wrappers keep their 3-arg signature.
    """
    # 1. Machine token — agents, daemons, adapters.
    if workspace.password_hash and token and token == workspace.password_hash:
        return True

    if db is None:
        db = SqlaSession.object_session(workspace)

    # 2. The owner, by verified identity.
    if db is not None and is_workspace_owner(db, workspace, authorization):
        return True

    return False
