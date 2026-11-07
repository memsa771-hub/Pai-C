"""Reviewers: each has an identity and a personal token (P2-D15). The token is shown once; only its hash is stored.
Tokens are random 256-bit values, so a plain SHA-256 is enough (there is nothing to guess or brute-force)."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from sqlalchemy import Engine, func, select, update
from sqlalchemy.exc import IntegrityError

from app.os import models

R = models.reviewers
TOKEN_PREFIX = "rvt_"
REF = re.compile(r"^[a-z0-9][a-z0-9_.-]{1,63}$")


class ReviewerError(ValueError):
    """A reviewer change the store refuses (bad ref, role or kind; a ref already used)."""


@dataclass(frozen=True)
class Reviewer:
    id: int
    ref: str
    display_name: str
    role: str
    kind: str
    active: bool


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _reviewer(row) -> Reviewer:
    return Reviewer(row.id, row.ref, row.display_name, row.role, row.kind, row.active)


class ReviewerStore:
    def __init__(self, engine: Engine, tenant_id: str) -> None:
        self.engine = engine
        self.tenant_id = tenant_id

    def add(self, ref: str, display_name: str, role: str, kind: str = "person") -> tuple[Reviewer, str]:
        """(the reviewer, the token). The token cannot be read again; `rotate` makes a new one."""
        if not REF.match(ref):
            raise ReviewerError("ref must be 2-64 characters: lower-case letters, digits, '_', '.', '-'")
        if role not in models.REVIEWER_ROLES:
            raise ReviewerError(f"role must be one of {models.REVIEWER_ROLES}")
        if kind not in models.REVIEWER_KINDS:
            raise ReviewerError(f"kind must be one of {models.REVIEWER_KINDS}")
        if not display_name.strip():
            raise ReviewerError("display name is required")
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        try:
            with self.engine.begin() as conn:
                row = conn.execute(R.insert().values(
                    tenant_id=self.tenant_id, ref=ref, display_name=display_name.strip(), role=role, kind=kind,
                    token_hash=_hash(token)).returning(R)).one()
        except IntegrityError:
            raise ReviewerError(f"reviewer '{ref}' already exists") from None
        return _reviewer(row), token

    def authenticate(self, token: str | None) -> Reviewer | None:
        """The active reviewer holding this token, else None."""
        token = (token or "").strip()
        if not token.startswith(TOKEN_PREFIX):
            return None
        with self.engine.connect() as conn:
            row = conn.execute(select(R).where(R.c.tenant_id == self.tenant_id, R.c.token_hash == _hash(token),
                                               R.c.active.is_(True))).first()
        if row is None or not hmac.compare_digest(row.token_hash, _hash(token)):
            return None
        return _reviewer(row)

    def get(self, ref: str) -> Reviewer | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(R).where(R.c.tenant_id == self.tenant_id, R.c.ref == ref)).first()
        return _reviewer(row) if row else None

    def by_id(self, reviewer_id: int) -> Reviewer | None:
        with self.engine.connect() as conn:
            row = conn.execute(select(R).where(R.c.tenant_id == self.tenant_id, R.c.id == reviewer_id)).first()
        return _reviewer(row) if row else None

    def list(self) -> list[Reviewer]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(R).where(R.c.tenant_id == self.tenant_id).order_by(R.c.id)).all()
        return [_reviewer(r) for r in rows]

    def set_active(self, ref: str, active: bool) -> bool:
        """Disables or enables a reviewer. Their past checks stay. False if there is no such reviewer."""
        with self.engine.begin() as conn:
            r = conn.execute(update(R).where(R.c.tenant_id == self.tenant_id, R.c.ref == ref).values(
                active=active, disabled_at=None if active else func.now()).returning(R.c.id))
            return r.first() is not None

    def rotate(self, ref: str) -> str | None:
        """A new token for the reviewer; the old one stops working at once. None if there is no such reviewer."""
        token = TOKEN_PREFIX + secrets.token_urlsafe(32)
        with self.engine.begin() as conn:
            r = conn.execute(update(R).where(R.c.tenant_id == self.tenant_id, R.c.ref == ref)
                             .values(token_hash=_hash(token)).returning(R.c.id))
            return token if r.first() is not None else None
