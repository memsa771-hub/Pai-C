"""Provider-neutral authenticated identity contract."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AuthenticatedIdentity:
    provider: str
    subject: str
    email: str
    email_verified: bool
    display_name: str | None = None
    # How the person signed in ("password", "google.com", ...).
    sign_in_provider: str = ""

    @property
    def needs_email_verification(self) -> bool:
        """Email/password accounts must prove the address before using the app."""
        return self.sign_in_provider == "password" and not self.email_verified
