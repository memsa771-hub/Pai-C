"""Deterministic checks for externally researched admission facts.

Search rank and model confidence are never evidence of an official rule. A
row is verified only after all checks pass against recorded page observations.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import ipaddress
import re
from urllib.parse import urlsplit


def _host(url: str) -> str | None:
    try:
        parsed = urlsplit(str(url or ""))
        host = (parsed.hostname or "").rstrip(".").casefold().encode("idna").decode("ascii")
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            return None
        if host in {"localhost"} or "." not in host:
            return None
        try:
            ipaddress.ip_address(host)
            return None
        except ValueError:
            return host
    except (ValueError, UnicodeError):
        return None


def official_url(url: str, domains: set[str] | frozenset[str]) -> bool:
    host = _host(url)
    return bool(host and any(host == domain or host.endswith("." + domain)
                             for domain in domains if _host("https://" + domain) == domain))


def _utc(value: datetime | str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
        return parsed.astimezone(timezone.utc) if parsed and parsed.tzinfo else None
    except ValueError:
        return None


def _number(value) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def _valid_claim(claim: dict) -> bool:
    if not isinstance(claim, dict) or not all(claim.get(key) for key in
                                              ("field", "source_url", "quote", "checked_at")):
        return False
    if claim.get("value") is None or _utc(claim["checked_at"]) is None:
        return False
    kind = claim.get("kind", "requirement")
    value = claim["value"]
    if kind == "fee":
        return (isinstance(value, dict) and _number(value.get("amount")) is not None
                and _number(value["amount"]) >= 0 and
                isinstance(value.get("currency"), str) and
                bool(re.fullmatch(r"[A-Z]{3}", value["currency"])) and
                value.get("basis") in {"per_year", "per_semester", "total", "per_credit"})
    if kind == "deadline":
        try:
            date.fromisoformat(value)
            return True
        except (TypeError, ValueError):
            return False
    if claim.get("comparator") in {"gte", "lte"}:
        if _number(claim.get("threshold")) is None:
            return False
        if claim.get("unit") is None and claim.get("scale") is None:
            return False
    return isinstance(value, (str, int, float, dict)) and not isinstance(value, bool)


def _matches(first: dict, second: dict) -> bool:
    a, b = first.get("value"), second.get("value")
    if isinstance(a, dict) and isinstance(b, dict):
        if (a.get("currency"), a.get("basis")) != (b.get("currency"), b.get("basis")):
            return False
        amount_a, amount_b = _number(a.get("amount")), _number(b.get("amount"))
        if amount_a is None or amount_b is None:
            return False
        return abs(amount_a - amount_b) <= max(Decimal("1"), abs(amount_a) * Decimal("0.01"))
    number_a, number_b = _number(a), _number(b)
    if number_a is not None and number_b is not None:
        return number_a == number_b
    return str(a).strip().casefold() == str(b).strip().casefold()


@dataclass(frozen=True)
class VerificationResult:
    status: str
    cycle_label: str | None
    checks: dict[str, dict]


class SourceVerifier:
    def __init__(self, *, freshness_days: int = 30, deadline_freshness_days: int = 7):
        self.freshness_days = freshness_days
        self.deadline_freshness_days = deadline_freshness_days

    def verify(self, *, claims: list[dict], source_url: str,
               official_domains: set[str] | frozenset[str], intake: str | None,
               page_text: str, checked_at: datetime,
               corroboration: list[dict] | None = None,
               corroborated_at: datetime | None = None,
               now: datetime | None = None) -> VerificationResult:
        now = _utc(now or datetime.now(timezone.utc))
        checked = _utc(checked_at)
        claims = claims or []
        official = bool(official_domains and official_url(source_url, official_domains)
                        and all(official_url(row.get("source_url", ""), official_domains)
                                for row in claims))
        target_years = set(re.findall(r"\b(?:19|20)\d{2}\b", intake or ""))
        page_years = set(re.findall(r"\b(?:19|20)\d{2}\b", page_text or ""))
        conflicting_cycle = bool(target_years and page_years and not (target_years & page_years))
        schema = bool(claims and all(_valid_claim(row) and row["quote"] in page_text
                                     for row in claims))
        key_claims = [row for row in claims if row.get("kind") in {"fee", "deadline"}
                      or row.get("comparator") in {"gte", "lte", "eq"}]
        by_field = {(row.get("kind", "requirement"), row.get("field")): row
                    for row in (corroboration or []) if isinstance(row, dict)}
        observed_later = _utc(corroborated_at)
        agreement = bool(key_claims and observed_later
                         and checked and observed_later > checked and observed_later <= now and all(
                             (other := by_field.get((row.get("kind", "requirement"), row.get("field"))))
                             and official_url(other.get("source_url", ""), official_domains)
                             and _utc(other.get("checked_at")) == observed_later
                             and (other.get("source_url") != row.get("source_url")
                                  or observed_later > checked + timedelta(hours=1))
                             and _valid_claim(other) and _matches(row, other)
                             for row in key_claims))
        deadlines = [date.fromisoformat(row["value"]) for row in claims
                     if row.get("kind") == "deadline" and _valid_claim(row)]
        urgent = any(0 <= (day - now.date()).days <= 60 for day in deadlines)
        window = self.deadline_freshness_days if urgent else self.freshness_days
        fresh = bool(checked and now - timedelta(days=window) <= checked <= now)
        checks = {
            "official_source": {"passed": official, "reason": "Source is not on a trusted institution domain" if not official else None},
            "current_cycle": {"passed": not conflicting_cycle, "reason": "Page describes an older cycle" if conflicting_cycle else None},
            "schema": {"passed": schema, "reason": "One or more facts lack a valid value, unit, date, quote or source" if not schema else None},
            "agreement": {"passed": agreement, "reason": "Awaiting a matching later official observation" if not agreement else None},
            "freshness": {"passed": fresh, "reason": "Source check is too old for the deadline" if not fresh else None},
        }
        return VerificationResult("verified" if all(item["passed"] for item in checks.values())
                                  else "unconfirmed", next(iter(sorted(target_years)), None), checks)
