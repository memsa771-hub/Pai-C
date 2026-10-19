"""Settings for the PAI OS. Reads only the env mapping it is given (or os.environ)."""

import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class OsSettings:
    database_url: str
    dbos_system_schema: str = "dbos"
    model_cheap: str = "gpt-5.4-mini"
    model_strong: str = "gpt-5.4"
    openai_api_key: str | None = None
    os_enabled: bool = False
    tenant_id: str = "pai"
    admin_token: str | None = None
    email_sender: str = "log"
    worker_id: str | None = None
    fetch_host_interval_s: float = 2.0  # research: minimum seconds between requests to one host
    page_ttl_h: float = 24.0  # research: how long a fetched page is reused
    page_max_bytes: int = 5_000_000  # research: larger pages are refused


def load_settings(env: Mapping[str, str] | None = None) -> OsSettings:
    env = os.environ if env is None else env
    database_url = env.get("OS_DATABASE_URL") or env.get("DATABASE_URL")
    if not database_url:
        raise ValueError("OS_DATABASE_URL or DATABASE_URL must be set")
    return OsSettings(
        database_url=database_url,
        dbos_system_schema=env.get("OS_DBOS_SYSTEM_SCHEMA", "dbos"),
        model_cheap=env.get("OS_MODEL_CHEAP", "gpt-5.4-mini"),
        model_strong=env.get("OS_MODEL_STRONG", "gpt-5.4"),
        openai_api_key=env.get("OS_OPENAI_API_KEY") or None,
        os_enabled=env.get("OS_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"},
        tenant_id=env.get("OS_TENANT_ID") or "pai",
        admin_token=env.get("OS_ADMIN_TOKEN") or None,
        email_sender=env.get("OS_EMAIL_SENDER") or "log",
        worker_id=env.get("OS_WORKER_ID") or None,
        fetch_host_interval_s=float(env.get("OS_FETCH_HOST_INTERVAL_S") or 2.0),
        page_ttl_h=float(env.get("OS_PAGE_TTL_H") or 24.0),
        page_max_bytes=int(env.get("OS_PAGE_MAX_BYTES") or 5_000_000),
    )
