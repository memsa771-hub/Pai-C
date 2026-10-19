"""Shared export redaction; never reads files or logs payloads."""
import re
from datetime import date, datetime

_PRIVATE_KEY = re.compile(r"email|password|secret|token|credential|authorization|api[_-]?key", re.I)
_ENV_SECRET = re.compile(r"(?:^|_)(?:KEY|TOKEN|PASSWORD|SECRET|EMAIL)$", re.I)
_EMAIL = re.compile(r"[\w.!#$%&'*+/=?^`{|}~-]+@[\w.-]+\.[a-zA-Z]{2,}")
_CREDENTIAL = re.compile(
    r"(?i)\b(?:password|secret|(?:access[_ -]?|refresh[_ -]?)?token|api[_ -]?key|authorization)"
    r"\s*(?:[:=]|\bis\b)\s*(?:\"[^\"]*\"|'[^']*'|\S+)|\bBearer\s+\S+|"
    r"\bsk-[\w-]+|\beyJ[\w-]+\.[\w-]+\.[\w-]+|"
    r"[a-z][a-z0-9+.-]*://[^\s/@:]+:[^\s/@]+@|"
    r"-----BEGIN [^-]*PRIVATE KEY-----[\s\S]*?-----END [^-]*PRIVATE KEY-----")

def redact(value, secrets=()):
    if isinstance(value, dict):
        return {str(k): redact(v, secrets) for k, v in value.items()
                if not _PRIVATE_KEY.search(str(k))}
    if isinstance(value, (list, tuple)):
        return [redact(v, secrets) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return _EMAIL.sub("[REDACTED]", _CREDENTIAL.sub("[REDACTED]", value))
    return value

