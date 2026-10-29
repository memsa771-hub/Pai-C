"""The monthly embeddings budget: an estimated spend counter and its cap.

The gateway asks `embedding_allowed()` before every embedding call and reports
each successful call with `record_embedding()`. Spend is an estimate (characters
/ chars_per_token, times the per-model rate in pai_c/policy/embedding_costs.json)
kept in one `pai_usage_months` row per scope and UTC month. At
PAI_EMBEDDING_MONTHLY_CAP_USD the gateway returns no vectors and recall falls
back to lexical search; the cap is logged once per process, not per call.

The counter uses its own short session (the gateway has none) and fails closed:
if the month's spend cannot be read, no embedding call is made.
"""
import json
import logging
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.config import config

logger = logging.getLogger(__name__)
SCOPE = "embeddings"
_COSTS = Path(__file__).resolve().parents[1] / "pai_c" / "policy" / "embedding_costs.json"
_cap_logged = False


@lru_cache(maxsize=1)
def embedding_costs() -> dict:
    return json.loads(_COSTS.read_text(encoding="utf-8"))


def rate_per_million(model: str) -> float:
    rates = embedding_costs()["usd_per_million_tokens"]
    return float(rates.get(model, rates["default"]))


def estimate_usd(model: str, texts: list[str]) -> float:
    tokens = sum(len(text or "") for text in texts) / embedding_costs()["chars_per_token"]
    return tokens * rate_per_million(model) / 1_000_000


def _month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def embedding_allowed() -> bool:
    global _cap_logged
    from app.database import new_session
    from app.models import PaiUsageMonth
    try:
        with new_session() as db:
            spent = db.scalar(select(PaiUsageMonth.est_usd).where(
                PaiUsageMonth.scope == SCOPE, PaiUsageMonth.month == _month())) or 0.0
    except Exception:
        logger.warning("embeddings: usage counter unreadable, no embedding call", exc_info=True)
        return False
    if float(spent) < config.PAI_EMBEDDING_MONTHLY_CAP_USD:
        return True
    if not _cap_logged:
        _cap_logged = True
        logger.warning("embeddings: monthly cap reached (est $%.4f of $%.2f); recall is lexical until next month",
                       float(spent), config.PAI_EMBEDDING_MONTHLY_CAP_USD)
    return False


def record_embedding(model: str, texts: list[str]) -> None:
    from app.database import new_session
    from app.models import PaiUsageMonth
    usd, month = estimate_usd(model, texts), _month()
    bump = (update(PaiUsageMonth).where(PaiUsageMonth.scope == SCOPE, PaiUsageMonth.month == month)
            .values(calls=PaiUsageMonth.calls + 1, est_usd=PaiUsageMonth.est_usd + usd,
                    updated_at=datetime.now(timezone.utc)))
    try:
        with new_session() as db:
            if db.execute(bump).rowcount == 0:
                try:
                    db.add(PaiUsageMonth(id=str(uuid.uuid4()), scope=SCOPE, month=month, calls=1, est_usd=usd))
                    db.flush()
                except IntegrityError:  # another process opened the month first
                    db.rollback()
                    db.execute(bump)
            db.commit()
    except Exception:
        logger.warning("embeddings: usage not recorded", exc_info=True)
