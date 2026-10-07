"""Provider-neutral web research tools with bounded retries and disposable cache."""

import asyncio
import hashlib
import json

import httpx

from app.config import config
from app.infrastructure.cache import get_bytes, set_bytes
from app.tools.web_search import get_web_search_provider


async def fetch(ctx, args):
    return await ctx.api.post("/v1/fetch", actor=ctx.source, json={
        "network": ctx.workspace_id,
        "url": args["url"], "mode": args.get("mode", "auto"),
        "max_chars": args.get("max_chars", 20000),
    })


async def institution_registry(ctx, args):
    from app.plugins._shared.institution_registry import resolve_institution

    return {"ok": True, "data": {"identity": await resolve_institution(args["url"])}}


async def search(ctx, args):
    provider = get_web_search_provider()
    if provider is None:
        return {"ok": False, "error": {"code": "search_not_configured",
                                       "message": "Web search is not configured"}}
    query = str(args["query"]).strip()[:500]
    if not query:
        return {"ok": False, "error": {"code": "invalid_query", "message": "Search query is empty"}}
    limit = max(1, min(int(args.get("limit", 5)), 20))
    identity = f"{type(provider).__module__}.{type(provider).__qualname__}:{getattr(provider, 'base_url', '')}"
    digest = hashlib.sha256(f"{identity}\0{query}\0{limit}".encode()).hexdigest()
    cache_key = f"websearch:v1:{digest}"
    cached = get_bytes(cache_key)
    if cached:
        try:
            return {"ok": True, "results": json.loads(cached), "cached": True}
        except (ValueError, TypeError):
            pass
    attempts = max(1, min(config.WEB_SEARCH_MAX_RETRIES + 1, 5))
    for attempt in range(attempts):
        try:
            results = await provider.search(query, limit)
            if not isinstance(results, list):
                raise ValueError("Search provider returned an invalid result")
            set_bytes(cache_key, json.dumps(results).encode(),
                      max(1, config.WEB_SEARCH_CACHE_TTL_SECONDS))
            return {"ok": True, "results": results, "cached": False}
        except (httpx.HTTPStatusError, httpx.TransportError, TimeoutError) as exc:
            retryable = (not isinstance(exc, httpx.HTTPStatusError)
                         or exc.response.status_code == 429 or exc.response.status_code >= 500)
            if not retryable or attempt + 1 >= attempts:
                return {"ok": False, "error": {"code": "search_provider_failed",
                                               "message": "Web search provider is temporarily unavailable"}}
            retry_after = 0.0
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    retry_after = float(exc.response.headers.get("Retry-After", "0"))
                except ValueError:
                    pass
            await asyncio.sleep(min(5.0, max(retry_after, 0.5 * 2 ** attempt)))
        except (TypeError, ValueError):
            return {"ok": False, "error": {"code": "search_provider_invalid_response",
                                           "message": "Web search returned an invalid response"}}
    return {"ok": False, "error": {"code": "search_provider_failed",
                                   "message": "Web search provider is temporarily unavailable"}}
