"""Settings for the PAI OS. Reads only the env mapping it is given (or os.environ)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class OsSettings:
    database_url: str
    dbos_system_schema: str = "dbos"
    model_cheap: str = "gpt-5.4-mini"
    model_strong: str = "gpt-5.4"
    openai_api_key: str | None = field(default=None, repr=False)  # never logged, never in a message
    os_enabled: bool = False
    tenant_id: str = "pai"
    admin_token: str | None = None
    email_sender: str = "log"
    resend_api_key: str | None = field(default=None, repr=False)  # Slice 9a: never logged, never in a message (OS_RESEND_API_KEY)
    email_from: str | None = None  # Slice 9a: the From address for Resend (OS_EMAIL_FROM)
    email_allowlist: frozenset[str] = frozenset()  # Slice 9a: exact addresses, lower-cased; empty = nobody
    worker_id: str | None = None
    fetch_host_interval_s: float = 2.0  # research: minimum seconds between requests to one host
    page_ttl_h: float = 24.0  # research: how long a fetched page is reused
    page_max_bytes: int = 5_000_000  # research: larger pages are refused
    # List prices, USD per 1M tokens (parent §9; cheap checked 2026-10-13, strong 2026-10-21 on
    # developers.openai.com/api/docs/pricing, under 272K context). None = not known yet: cost() refuses.
    price_cheap_in: float | None = 0.75
    price_cheap_cached: float | None = 0.075
    price_cheap_out: float | None = 4.50
    price_strong_in: float | None = 2.50
    price_strong_cached: float | None = 0.25
    price_strong_out: float | None = 15.00
    research_monthly_usd: float = 20.0  # research spend cap per tenant and month (S2-D10)
    documents_monthly_usd: float = 10.0  # document reading spend cap per tenant and month (S3-D11)
    statements_monthly_usd: float = 10.0  # Writer + Critic spend cap per tenant and month (S5-D10)
    replan_monthly_usd: float = 5.0  # Supervisor spend cap per tenant and month (Slice 7 S7-D8)
    fact_ttl_days: int = 30  # a confirmed fact older than this goes stale (spec §4.7)
    rehearsal: bool = False  # Slice 9a rehearsal mode: stored clock offset, no cron, admin advance/tick (spec §2.2)
    model_mode: str = "openai"  # Slice 9a: "openai", or "offline" (canned answers, rehearsal only; spec §2.3)
    offline_answers_dir: str | None = None  # the canned answers' folder (offline mode only)


TRUTHY = {"1", "true", "yes", "on"}
MODEL_MODES = ("openai", "offline")


class ModelModeError(ValueError):
    """OS_MODEL_MODE is unknown, or offline without rehearsal mode or an answers folder: the OS must not start."""


def flag(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in TRUTHY


def _price(env: Mapping[str, str], name: str, default: float | None) -> float | None:
    raw = env.get(name)
    return float(raw) if raw else default


def load_settings(env: Mapping[str, str] | None = None) -> OsSettings:
    env = os.environ if env is None else env
    database_url = env.get("OS_DATABASE_URL") or env.get("DATABASE_URL")
    if not database_url:
        raise ValueError("OS_DATABASE_URL or DATABASE_URL must be set")
    model_mode = (env.get("OS_MODEL_MODE") or "openai").strip().lower()
    answers_dir = (env.get("OS_OFFLINE_ANSWERS_DIR") or "").strip() or None
    if model_mode not in MODEL_MODES:
        raise ModelModeError(f"OS_MODEL_MODE must be one of {', '.join(MODEL_MODES)}, got {model_mode!r}")
    if model_mode == "offline" and not flag(env, "OS_REHEARSAL"):  # canned answers never reach a real student
        raise ModelModeError("OS_MODEL_MODE=offline needs rehearsal mode: set OS_REHEARSAL=on, or use OS_MODEL_MODE=openai")
    if model_mode == "offline" and answers_dir is None:
        raise ModelModeError("OS_MODEL_MODE=offline needs OS_OFFLINE_ANSWERS_DIR (the folder of canned answers)")
    email_sender = env.get("OS_EMAIL_SENDER") or "log"
    resend_api_key = (env.get("OS_RESEND_API_KEY") or "").strip() or None
    email_from = (env.get("OS_EMAIL_FROM") or "").strip() or None
    if email_sender == "resend" and (resend_api_key is None or email_from is None):
        raise ValueError("OS_EMAIL_SENDER=resend needs OS_RESEND_API_KEY and OS_EMAIL_FROM")
    allowlist = frozenset(a.strip().lower() for a in (env.get("OS_EMAIL_ALLOWLIST") or "").split(",") if a.strip())
    return OsSettings(
        database_url=database_url,
        dbos_system_schema=env.get("OS_DBOS_SYSTEM_SCHEMA", "dbos"),
        model_cheap=env.get("OS_MODEL_CHEAP", "gpt-5.4-mini"),
        model_strong=env.get("OS_MODEL_STRONG", "gpt-5.4"),
        openai_api_key=env.get("OS_OPENAI_API_KEY") or None,
        os_enabled=flag(env, "OS_ENABLED"),
        tenant_id=env.get("OS_TENANT_ID") or "pai",
        admin_token=env.get("OS_ADMIN_TOKEN") or None,
        email_sender=email_sender,
        resend_api_key=resend_api_key,
        email_from=email_from,
        email_allowlist=allowlist,
        worker_id=env.get("OS_WORKER_ID") or None,
        fetch_host_interval_s=float(env.get("OS_FETCH_HOST_INTERVAL_S") or 2.0),
        page_ttl_h=float(env.get("OS_PAGE_TTL_H") or 24.0),
        page_max_bytes=int(env.get("OS_PAGE_MAX_BYTES") or 5_000_000),
        price_cheap_in=_price(env, "OS_PRICE_CHEAP_IN", 0.75),
        price_cheap_cached=_price(env, "OS_PRICE_CHEAP_CACHED", 0.075),
        price_cheap_out=_price(env, "OS_PRICE_CHEAP_OUT", 4.50),
        price_strong_in=_price(env, "OS_PRICE_STRONG_IN", 2.50),
        price_strong_cached=_price(env, "OS_PRICE_STRONG_CACHED", 0.25),
        price_strong_out=_price(env, "OS_PRICE_STRONG_OUT", 15.00),
        research_monthly_usd=float(env.get("OS_RESEARCH_MONTHLY_USD") or 20.0),
        documents_monthly_usd=float(env.get("OS_DOCUMENTS_MONTHLY_USD") or 10.0),
        statements_monthly_usd=float(env.get("OS_STATEMENTS_MONTHLY_USD") or 10.0),
        replan_monthly_usd=float(env.get("OS_REPLAN_MONTHLY_USD") or 5.0),
        fact_ttl_days=int(env.get("OS_FACT_TTL_DAYS") or 30),
        rehearsal=flag(env, "OS_REHEARSAL"),
        model_mode=model_mode,
        offline_answers_dir=answers_dir,
    )
