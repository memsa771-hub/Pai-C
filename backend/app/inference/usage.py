"""The monthly embeddings budget: an estimated spend counter and its cap.

The gateway asks `embedding_allowed()` before every embedding call and reports
each successful call with `record_embedding()`. Spend is an estimate (characters
/ chars_per_token, times the per-model rate in pai_c/policy/embedding_costs.json)
kept in one `pai_usage_months` row per scope and UTC month. At
PAI_EMBEDDING_MONTHLY_CAP_USD the gateway returns no vectors and recall falls
back to lexical search; the cap is logged once per process and month, not per call.

The counter uses its own short session (the gateway has none) and fails closed:
if the month's spend cannot be read, no embedding call is made.

Every other model call is recorded too, one row per role (`models:<role>`),
priced from pai_c/policy/model_costs.json. Together with embeddings they make
the one monthly spend that `cap_state()` compares with PAI_MONTHLY_CAP_USD;
model_roles.json says at which share of the cap which roles stop. That check
fails open: an unreadable counter must not silence the counselor.
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
MODELS_SCOPE = "models"
_POLICY = Path(__file__).resolve().parents[1] / "pai_c" / "policy"
_COSTS = _POLICY / "embedding_costs.json"
_MODEL_COSTS = _POLICY / "model_costs.json"
_cap_logged = ""  # the month the cap was last logged for
_gate_logged: dict[str, str] = {}  # role -> the UTC day its skip was last logged


@lru_cache(maxsize=1)
def embedding_costs() -> dict:
    return json.loads(_COSTS.read_text(encoding="utf-8"))


def rate_per_million(model: str) -> float:
    rates = embedding_costs()["usd_per_million_tokens"]
    return float(rates.get(model, rates["default"]))


def estimate_usd(model: str, texts: list[str], tokens: int | None = None) -> float:
    """The provider's token count when it reports one, else chars / chars_per_token."""
    if not isinstance(tokens, int) or isinstance(tokens, bool):
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
    if _cap_logged != _month():
        _cap_logged = _month()
        logger.warning("embeddings: monthly cap reached (est $%.4f of $%.2f); recall is lexical until next month",
                       float(spent), config.PAI_EMBEDDING_MONTHLY_CAP_USD)
    return False


def _bump(scope: str, usd: float) -> None:
    """Add one call and its estimate to the scope's row for this month."""
    from app.database import new_session
    from app.models import PaiUsageMonth
    month = _month()
    bump = (update(PaiUsageMonth).where(PaiUsageMonth.scope == scope, PaiUsageMonth.month == month)
            .values(calls=PaiUsageMonth.calls + 1, est_usd=PaiUsageMonth.est_usd + usd,
                    updated_at=datetime.now(timezone.utc)))
    with new_session() as db:
        if db.execute(bump).rowcount == 0:
            try:
                db.add(PaiUsageMonth(id=str(uuid.uuid4()), scope=scope, month=month, calls=1, est_usd=usd))
                db.flush()
            except IntegrityError:  # another process opened the month first
                db.rollback()
                db.execute(bump)
        db.commit()


def record_embedding(model: str, texts: list[str], tokens: int | None = None) -> None:
    try:
        _bump(SCOPE, estimate_usd(model, texts, tokens))
    except Exception:
        logger.warning("embeddings: usage not recorded", exc_info=True)


@lru_cache(maxsize=1)
def model_costs() -> dict:
    return json.loads(_MODEL_COSTS.read_text(encoding="utf-8"))


def model_rates(model: str) -> dict:
    rates = model_costs()["usd_per_million_tokens"]
    return rates.get(model) or rates["default"]


def estimate_model_usd(model: str, usage) -> float:
    """OpenAI-shaped usage (the Anthropic transport reshapes its own): cache
    reads and cache writes are billed at their own rates (a model without a
    cache_write rate pays the input rate), the rest of the input at the input rate."""
    if usage is None:
        return 0.0
    details = getattr(usage, "prompt_tokens_details", None)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    cached = int(getattr(details, "cached_tokens", 0) or 0)
    written = int(getattr(details, "cache_write_tokens", 0) or 0)
    output = int(getattr(usage, "completion_tokens", 0) or 0)
    rates = model_rates(model)
    return (max(0, prompt - cached - written) * rates["input"] + cached * rates["cached_input"]
            + written * rates.get("cache_write", rates["input"]) + output * rates["output"]) / 1_000_000


def record_model_call(role: str, model: str, usage) -> None:
    try:
        _bump(f"{MODELS_SCOPE}:{role}", estimate_model_usd(model, usage))
    except Exception:
        logger.warning("models: usage not recorded role=%s", role, exc_info=True)


def month_rows(month: str | None = None) -> list[tuple[str, int, float]]:
    """(scope, calls, est_usd) for every scope counted against the monthly cap."""
    from app.database import new_session
    from app.models import PaiUsageMonth
    with new_session() as db:
        rows = db.execute(select(PaiUsageMonth.scope, PaiUsageMonth.calls, PaiUsageMonth.est_usd)
                          .where(PaiUsageMonth.month == (month or _month()))).all()
    return [(scope, int(calls or 0), float(usd or 0.0)) for scope, calls, usd in rows
            if scope == SCOPE or scope.startswith(MODELS_SCOPE + ":")]


def _roles_policy() -> dict:
    from app.inference.gateway import model_roles
    return model_roles()


def cap_state() -> dict:
    """{month, spent, cap, stage}: stage is the highest of model_roles.json's
    cap_stages the month's spend has reached, else "ok"."""
    month, cap = _month(), float(config.PAI_MONTHLY_CAP_USD)
    try:
        spent = sum(usd for _, _, usd in month_rows(month))
    except Exception:
        logger.warning("models: usage counter unreadable, cap not applied", exc_info=True)
        return {"month": month, "spent": None, "cap": cap, "stage": "ok"}
    stage = "ok"
    for name, share in sorted(_roles_policy()["cap_stages"].items(), key=lambda item: item[1]):
        if cap <= 0 or spent >= share * cap:
            stage = name
    return {"month": month, "spent": spent, "cap": cap, "stage": stage}


def stopped_roles(stage: str) -> set[str]:
    """Each stage stops its own roles and every lower stage's roles."""
    stages = _roles_policy()["cap_stages"]
    if stage not in stages:
        return set()
    gates = _roles_policy()["cap_gates"]
    return {role for name, share in stages.items() if share <= stages[stage] for role in gates.get(name, [])}


def role_allowed(role: str) -> bool:
    """False when the month's spend has reached the stage that stops `role`.
    A stopped role is logged once per UTC day, not per call."""
    state = cap_state()
    if role not in stopped_roles(state["stage"]):
        return True
    today = datetime.now(timezone.utc).date().isoformat()
    if _gate_logged.get(role) != today:
        _gate_logged[role] = today
        logger.warning("models: %s stopped at cap stage %s (est $%.2f of $%.2f)",
                       role, state["stage"], state["spent"] or 0.0, state["cap"])
    return False


def paused_line() -> str:
    return _roles_policy()["copy"]["paused_line"]
