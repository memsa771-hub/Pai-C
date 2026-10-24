# -*- coding: utf-8 -*-
"""
Placement AI Workspace Backend — FastAPI entry point.

A workspace is an ONM network with workspace-specific mods loaded.
"""

import asyncio
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import config
from app.security.errors import EmailNotVerified, IdentityUnavailable
from app.api.response import ResponseCode, json_response
from app.routers import counselor_possibilities, account, app_version, auth, counselor_summary, counselor_voice, decision_records, escalations, events, feedback, fetch, files, network, notifications, operator, roadmaps, search, shares, student_profile, student_requests, tasks, vault, workflows, workspaces

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


MAINTENANCE_INTERVAL_SECONDS = 300


def _run_maintenance():
    """Expire old notifications and auto-archive stale threads.

    Pure synchronous DB work in a short-lived session. Invoked via
    ``asyncio.to_thread`` so these table scans run off the event loop and the
    connection is released the moment the sweep finishes. The archive scan is
    backed by ``idx_channels_status_last_event`` so it's an index lookup, not
    a full-table scan.
    """
    from datetime import timedelta
    from sqlalchemy import update
    from app.database import SessionLocal
    from app.models import Channel, NotificationRecord

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # ── Expire old notifications (older than 7 days) ──
        seven_days_ago = now - timedelta(days=7)
        expired_notifs = db.execute(
            update(NotificationRecord)
            .where(
                NotificationRecord.status == "active",
                NotificationRecord.created_at < seven_days_ago,
            )
            .values(status="expired")
            .returning(NotificationRecord.id)
        ).fetchall()
        if expired_notifs:
            logger.info("Expired %d old notification(s)", len(expired_notifs))

        # ── Auto-archive stale threads (no activity for 30 days) ──
        stale_thread_cutoff = int((now - timedelta(days=30)).timestamp() * 1000)
        archived = db.execute(
            update(Channel)
            .where(
                Channel.status == "active",
                Channel.starred == False,  # noqa: E712
                Channel.last_event_at != None,  # noqa: E711
                Channel.last_event_at < stale_thread_cutoff,
            )
            .values(status="archived")
            .returning(Channel.id)
        ).fetchall()
        if archived:
            logger.info("Auto-archived %d stale thread(s)", len(archived))

        db.commit()
    finally:
        db.close()


async def _maintenance_loop():
    """Background loop: heavy expiry/archival scans every few minutes, run
    off the event loop via ``asyncio.to_thread``."""
    while True:
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(_run_maintenance)
        except Exception:
            logger.exception("Maintenance loop error")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("LIFESPAN: starting")
    config.validate_startup()
    from app.pai_c.playbooks.registry import BOOKS
    logger.info("counselor_playbooks_loaded count=%d", len(BOOKS))

    # Human sign-in (Firebase) is core, not optional: say so at boot rather
    # than let every sign-in fail with an obscure error.
    import os as _os
    if not config.FIREBASE_PROJECT_ID or not (config.FIREBASE_SERVICE_ACCOUNT
                                              or _os.environ.get("FIREBASE_AUTH_EMULATOR_HOST")):
        logger.error(
            "LIFESPAN: FIREBASE_PROJECT_ID/FIREBASE_SERVICE_ACCOUNT are not set — human "
            "sign-in will not work. Set them in workspace/.env (see workspace/.env.example)."
        )

    from app.services.pai import validate_config as validate_pai_config
    validate_pai_config()

    # Pay the OpenAI SDK's lazy `openai.resources` import here, on the main
    # thread at boot (~2s), instead of inside the first student's retrieval
    # budget on a worker thread — where it both blew the deadline and raced
    # the request thread's own import into a _DeadlockError.
    if config.PAI_MEMORY_CONTEXT_ENABLED:
        import app.memory.embeddings  # noqa: F401

    # Align the threadpool with the DB pool. All DB-bound handlers are `def`
    # (run via anyio's threadpool) while the per-worker connection pool holds
    # pool_size+max_overflow connections (40+8, see app/database.py). If the
    # threadpool admitted more concurrent DB requests than there are
    # connections, the excess would wait pool_timeout=2s then raise QueuePool
    # TimeoutError (500s). Capping tokens at exactly the pool capacity makes
    # bursts queue for a THREAD (cheap, unbounded wait) instead of stampeding
    # the pool. Env-overridable for ops.
    import anyio.to_thread
    default_tokens = config.DB_POOL_SIZE + config.DB_MAX_OVERFLOW
    tokens = int(os.environ.get("THREADPOOL_TOKENS", str(default_tokens)))
    anyio.to_thread.current_default_thread_limiter().total_tokens = tokens
    logger.info("LIFESPAN: threadpool capped at %d tokens (= DB pool capacity)", tokens)

    # Auto-create tables for SQLite (dev mode) — production uses Alembic.
    try:
        from app.database import engine, Base, _is_sqlite
        logger.info("LIFESPAN: database imported, _is_sqlite=%s", _is_sqlite)
        if _is_sqlite:
            from app import models  # noqa: F401 — ensure all models are registered
            Base.metadata.create_all(bind=engine)
            logger.info("SQLite: auto-created tables")
    except Exception as e:
        logger.error("LIFESPAN: database import failed: %s", e)

    logger.info("LIFESPAN: creating maintenance task")
    maintenance_task = asyncio.create_task(_maintenance_loop())

    logger.info("LIFESPAN: yielding (startup complete)")
    yield
    maintenance_task.cancel()
    try:
        await maintenance_task
    except asyncio.CancelledError:
        pass
    from app.infrastructure.cache import close_redis
    await close_redis()
    # Shutdown: close Playwright browser
    from app.browser.manager import BrowserManager
    await BrowserManager.get().shutdown()


IS_PRODUCTION = config.APP_ENV.strip().lower() == "production"

app = FastAPI(
    title="Placement AI Workspace",
    description="Placement AI student guidance and execution workspace",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# CORS — added FIRST so it's innermost in the stack. That way CORS
# headers (and OPTIONS preflight handling) are applied BEFORE gzip, so
# CORS-aware responses still work when compressed.
origins = [o.strip() for o in config.CORS_ORIGINS.split(",") if o.strip()]
if IS_PRODUCTION and origins != ["https://app.placement-ai.com"]:
    raise RuntimeError(
        "Production CORS_ORIGINS must be exactly https://app.placement-ai.com"
    )
desktop_origin = "pai://workspace"
allowed_origins = [*origins, desktop_origin]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip — Compresses all responses above `minimum_size` bytes when the
# client sends `Accept-Encoding: gzip`. Event polling responses are JSON
# and compress ~4-5x. Current egress is dominated by /v1/events poll
# bodies (~500GB/mo observed); gzip should cut that to ~100-130GB/mo.
# Level 6 is the standard tradeoff between CPU cost and ratio.
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=6)


class NoTransformCompressionHeadersMiddleware(BaseHTTPMiddleware):
    """Tell intermediate proxies not to transform compressed responses.

    Without these headers a CDN or proxy may decompress /v1/events responses,
    increasing bandwidth substantially.

    `no-transform` directs intermediaries not to modify the Content-Encoding
    (RFC 7234). `private` signals that the response is per-client (poll
    data is scoped by workspace token), so the CDN shouldn't cache and
    share across clients.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Don't override if the handler already set cache-control explicitly.
        if "cache-control" not in response.headers:
            response.headers["cache-control"] = "private, no-store, no-transform"
        return response


app.add_middleware(NoTransformCompressionHeadersMiddleware)


class PrivateApiMiddleware(BaseHTTPMiddleware):
    """API answers are per-student: never let a cache keep them.

    Authentication itself is the Firebase ID token each request carries as its
    Bearer, checked by the route (app.security.human_auth). There is no cookie,
    so there is no cross-site request to forge.
    """

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/v1/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response


app.add_middleware(PrivateApiMiddleware)


_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _safe_route_path(request: Request) -> str:
    """Use the route template; raw paths can themselves contain credentials."""
    route = request.scope.get("route")
    return getattr(route, "path", "<unmatched>")


class SafeAccessLogMiddleware(BaseHTTPMiddleware):
    """Log request shape without query strings, credentials, or request bodies."""

    async def dispatch(self, request: Request, call_next):
        supplied_id = request.headers.get("x-request-id", "")
        request_id = supplied_id if _REQUEST_ID_RE.fullmatch(supplied_id) else uuid.uuid4().hex
        started = time.monotonic()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        response.headers["x-content-type-options"] = "nosniff"
        response.headers["referrer-policy"] = "strict-origin-when-cross-origin"
        response.headers["content-security-policy"] = "frame-ancestors 'none'"
        response.headers["permissions-policy"] = "camera=(), microphone=(), geolocation=()"
        # Successful GET event polls are frequent; retain errors and mutations.
        if request.method != "GET" or response.status_code >= 400:
            logger.info(
                "request method=%s path=%s status=%s request_id=%s ms=%d",
                request.method,
                _safe_route_path(request),
                response.status_code,
                request_id,
                int((time.monotonic() - started) * 1000),
            )
        return response


app.add_middleware(SafeAccessLogMiddleware)


# Log Pydantic validation failures with the offending body so we can
# debug client/server schema drift from CloudWatch instead of guessing
# from a bare 422. Triggered any time FastAPI rejects a request body
# before the route handler sees it.
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse as _ValidationJSONResponse


def _redacted_validation_errors(exc: RequestValidationError) -> list[dict]:
    """What went wrong, never what was sent.

    Pydantic attaches the offending value to each error as `input` — and for a
    missing-field error at the body root, `input` is the ENTIRE request body.
    A request that carries a password or token could put that secret straight
    into the logs. `ctx` can quote
    values too.

    Keep the location and the failure type, which is all a developer needs to
    fix a client, and drop the payload.
    """
    redacted = []
    for error in exc.errors():
        redacted.append({
            "loc": [str(part) for part in error.get("loc", ())],
            "type": error.get("type"),
            "msg": error.get("msg"),
        })
    return redacted


@app.exception_handler(EmailNotVerified)
async def _email_not_verified(request: Request, exc: EmailNotVerified):
    """Signed in with email and password, but the address is not verified yet."""
    return json_response(ResponseCode.FORBIDDEN, "AUTH_EMAIL_NOT_VERIFIED")


@app.exception_handler(IdentityUnavailable)
async def _identity_unavailable(request: Request, exc: IdentityUnavailable):
    """We could not verify the caller, as distinct from refusing them.

    This must NOT be a 401. A client that receives 401 is right to conclude its
    session is over and sign the user out — that is exactly what both of our
    clients do. Answering 401 because Firebase was briefly unreachable would
    therefore sign a student out for our outage, mid-session, with nothing on
    screen to explain it. 503 says "ask again", which is the truth, and both
    clients treat it as retryable.
    """
    logger.warning("identity provider unavailable on %s", _safe_route_path(request))
    return json_response(
        ResponseCode.INTERNAL_ERROR,
        "Sign-in is temporarily unavailable. Please try again.",
        status_code=503,
    )


@app.exception_handler(RequestValidationError)
async def _log_validation_errors(request: Request, exc: RequestValidationError):
    safe_errors = _redacted_validation_errors(exc)
    logger.warning(
        "validation 422 path=%s errors=%s", _safe_route_path(request), safe_errors,
    )
    # The response is for the caller, who already knows what they sent — but it
    # is echoed into browser consoles and client logs, so it gets the same
    # treatment rather than handing the value back out.
    return _ValidationJSONResponse(
        status_code=422, content={"detail": safe_errors},
    )


async def _unexpected_error(request: Request, exc: Exception):
    """Keep internal exception details in server logs, never public responses."""
    request_id = request.headers.get("x-request-id", "")
    if not _REQUEST_ID_RE.fullmatch(request_id):
        request_id = uuid.uuid4().hex
    logger.error(
        "unhandled exception method=%s path=%s request_id=%s error_type=%s",
        request.method,
        _safe_route_path(request),
        request_id,
        type(exc).__name__,
    )
    response = json_response(
        ResponseCode.INTERNAL_ERROR,
        "Internal server error",
        status_code=500,
    )
    response.headers["x-request-id"] = request_id
    return response


if IS_PRODUCTION:
    app.add_exception_handler(Exception, _unexpected_error)


# Routers
app.include_router(account.router)
app.include_router(app_version.router)
app.include_router(decision_records.router)
app.include_router(escalations.router)
app.include_router(auth.router)
app.include_router(counselor_voice.router)
app.include_router(counselor_summary.router)
from app.routers import counselor_fact_cards, counselor_profile_cards, counselor_paths, counselor_health, counselor_workspace
app.include_router(counselor_fact_cards.router)
app.include_router(counselor_profile_cards.router)
app.include_router(counselor_paths.router)
app.include_router(counselor_health.router)
app.include_router(counselor_workspace.router)
app.include_router(counselor_possibilities.router)
app.include_router(events.router)
app.include_router(feedback.router)
app.include_router(fetch.router)
app.include_router(files.router)
app.include_router(network.router)
app.include_router(notifications.router)
app.include_router(operator.router)
app.include_router(roadmaps.router)
app.include_router(search.router)
app.include_router(shares.router)
app.include_router(student_profile.router)
app.include_router(student_requests.router)
app.include_router(tasks.router)
app.include_router(vault.router)
app.include_router(workflows.router)
app.include_router(workspaces.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
