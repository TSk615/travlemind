"""Bound Grok retries and fail over to Exa without losing upstream source sessions."""
from __future__ import annotations

import asyncio
import contextvars
import functools
import inspect
import logging
import math
import uuid
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

import httpx

_LOG = logging.getLogger(__name__)
_PRIMARY_STATE: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar("grok_primary_state", default=None)


def _deadline(value: float, maximum: float, name: str) -> None:
    if not math.isfinite(value) or not 0 < value <= maximum:
        raise ValueError(f"{name} timeout must be in (0, {maximum:g}] seconds")


def install_bounded_primary_search(server_module: Any, timeout_seconds: float = 40.0) -> None:
    _deadline(timeout_seconds, 60, "Grok primary search")
    provider = server_module.GrokSearchProvider
    original = provider.search
    if getattr(original, "_travelmind_bounded_primary_search", False):
        return

    @functools.wraps(original)
    async def bounded(self, *args, **kwargs):
        state = _PRIMARY_STATE.get()
        try:
            answer = await asyncio.wait_for(original(self, *args, **kwargs), timeout=timeout_seconds)
            if not str(answer or "").strip() and state is not None:
                state["failure"] = "empty_response"
            return answer
        except Exception as exc:
            # Cancellation deliberately propagates. Never log exception text/credentials.
            reason = "timeout" if isinstance(exc, asyncio.TimeoutError) else "upstream_error"
            if state is not None:
                state["failure"] = reason
            _LOG.warning("Grok primary search unavailable (%s)", reason)
            raise

    bounded._travelmind_bounded_primary_search = True
    provider.search = bounded


def _sources(rows: Any) -> list[dict[str, Any]]:
    """Only publish usable HTTP(S) evidence; do not echo arbitrary provider metadata."""
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        try:
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
                continue
        except ValueError:
            continue
        if url in seen:
            continue
        seen.add(url)
        result.append({
            "url": url,
            "title": str(row.get("title") or url)[:500],
            "content": str(row.get("content") or row.get("text") or row.get("snippet") or "")[:3000],
            "source": str(row.get("source") or "upstream")[:40],
        })
    return result


async def search_exa(query: str, api_key: str, *, timeout_seconds: float = 12.0,
                     transport: httpx.AsyncBaseTransport | None = None) -> list[dict[str, Any]]:
    """A single bounded request to the official endpoint; no key in URL or redirects."""
    async with httpx.AsyncClient(timeout=timeout_seconds, follow_redirects=False,
                                 trust_env=False, transport=transport) as client:
        response = await client.post(
            "https://api.exa.ai/search",
            headers={"x-api-key": api_key, "Content-Type": "application/json"},
            json={"query": query, "type": "auto", "numResults": 6,
                  "contents": {"text": {"maxCharacters": 2500}}},
        )
        response.raise_for_status()
        return _sources([{**row, "source": "exa"} for row in response.json().get("results", []) if isinstance(row, dict)])


def install_search_fallback(server_module: Any, *, exa_api_key: str = "",
                            primary_timeout_seconds: float = 40.0,
                            upstream_timeout_seconds: float = 45.0,
                            exa_timeout_seconds: float = 12.0,
                            exa_search: Callable[..., Awaitable[list[dict[str, Any]]]] = search_exa) -> None:
    """Wrap the module entry point used by InProcessGrokSearchRunner.

    Upstream catches Grok errors and gathers Tavily/Firecrawl in parallel. A
    request-local ContextVar records that swallowed failure. Bound the gather
    too, so an extra-source timeout cannot prevent Exa from starting. Defaults
    leave 18 seconds of margin under the backend's 75-second tool deadline.
    """
    _deadline(upstream_timeout_seconds, 50, "Upstream search")
    _deadline(exa_timeout_seconds, 15, "Exa fallback")
    install_bounded_primary_search(server_module, primary_timeout_seconds)
    original = server_module.web_search
    if getattr(original, "_travelmind_exa_fallback", False):
        return
    signature = inspect.signature(original)

    @functools.wraps(original)
    async def resilient(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        query = str(bound.arguments.get("query") or "").strip()
        state: dict[str, str] = {}
        token = _PRIMARY_STATE.set(state)
        payload: dict[str, Any] = {}
        try:
            try:
                raw = await asyncio.wait_for(original(*args, **kwargs), timeout=upstream_timeout_seconds)
                if isinstance(raw, dict):
                    payload = raw
            except Exception as exc:
                state["failure"] = "timeout" if isinstance(exc, asyncio.TimeoutError) else "upstream_error"
            session_id = str(payload.get("session_id") or "") or uuid.uuid4().hex
            existing = _sources(payload.get("sources"))
            if not existing and payload.get("session_id"):
                # Upstream normally returns only a session id and source count.
                cached = await server_module._SOURCES_CACHE.get(session_id)
                existing = _sources(cached)
            reason = state.get("failure")
            if not reason and str(payload.get("content") or "").strip() and existing:
                return payload  # Healthy Grok retains its original contract, with no Exa spend.
            reason = reason or "missing_sources"
            exa_sources: list[dict[str, Any]] = []
            if exa_api_key and query:
                try:
                    exa_sources = _sources(await asyncio.wait_for(
                        exa_search(query, exa_api_key, timeout_seconds=exa_timeout_seconds),
                        timeout=exa_timeout_seconds,
                    ))
                except Exception:
                    _LOG.warning("Exa fallback unavailable")
            merged = _sources(existing + exa_sources)
            await server_module._SOURCES_CACHE.set(session_id, merged)
            if exa_sources:
                content = "\n\n".join(f"{row['title']}\n{row['url']}\n{row['content']}" for row in exa_sources)
                return {**payload, "session_id": session_id, "content": content,
                        "sources": merged, "sources_count": len(merged),
                        "search_provider": "exa", "fallback_reason": reason}
            if existing:
                # Do not discard successful Tavily/Firecrawl evidence when Exa is down.
                content = "\n\n".join(f"{row['title']}\n{row['url']}\n{row['content']}" for row in existing)
                return {**payload, "session_id": session_id, "content": content,
                        "sources": existing, "sources_count": len(existing),
                        "search_provider": "upstream_sources", "fallback_reason": reason}
            return {"session_id": session_id, "content": "搜索暂时不可用，请稍后重试。",
                    "sources": [], "sources_count": 0, "error": "search_unavailable",
                    "fallback_reason": reason}
        finally:
            _PRIMARY_STATE.reset(token)

    resilient._travelmind_exa_fallback = True
    server_module.web_search = resilient
