"""The pilot-consent check an upload needs (Slice 9a spec §3.2), shared by the upload route and by the DocumentFiles
port's `register` (P1-T7) so both refuse the same way."""

from app.os.consent.store import ConsentStore
from app.os.consent.terms import current_terms

MESSAGES = {"terms_not_set": "the pilot terms are not written yet",
            "consent_needed": "Please agree to the pilot terms first."}


def accepts(svc, terms) -> bool:
    """Placeholder terms can be agreed to, and count, only in rehearsal mode (Slice 9a spec §3.2)."""
    return not terms.placeholder or svc.settings.rehearsal


def upload_refusal(svc, student: str) -> str | None:
    """None when the student may upload, else `terms_not_set` or `consent_needed`."""
    terms = current_terms(svc.terms_dir)
    if not accepts(svc, terms):  # a placeholder row made in a rehearsal never counts outside it
        return "terms_not_set"
    if not ConsentStore(svc.engine, svc.settings.tenant_id).has(student, terms.version):
        return "consent_needed"
    return None
