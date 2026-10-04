"""Provider-neutral authenticated identity contract."""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class AuthenticatedIdentity:
    provider: str
    subject: str
    email: str
    email_verified: bool
    display_name: str | None = None
    username: str | None = None


class IdentityVerifier(Protocol):
    def verify(self, token: str) -> AuthenticatedIdentity | None: ...


class SupabaseIdentityVerifier:
    def verify(self, token: str) -> AuthenticatedIdentity | None:
        from .human_auth import verify_supabase_claims
        claims = verify_supabase_claims(token)
        if not claims or not claims.get("supabase_uid"):
            return None
        return AuthenticatedIdentity(
            provider="supabase", subject=str(claims["supabase_uid"]),
            email=claims["email"],
            email_verified=bool(claims.get("email_verified", True)),
            display_name=claims.get("display_name"),
            username=claims.get("username"),
        )
