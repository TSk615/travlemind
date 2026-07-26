from __future__ import annotations

import asyncio
import hashlib
import hmac
import time
from dataclasses import dataclass

from fastapi import Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis

from travelmind_api.core.config import Settings


UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSRF_TOKEN_EXEMPT_PATHS = {"/api/v1/auth/login", "/api/v1/auth/register"}
RATE_LIMIT_SCRIPT = """
local current = redis.call('INCR', KEYS[1])
if current == 1 then
  redis.call('EXPIRE', KEYS[1], ARGV[1])
end
local ttl = redis.call('TTL', KEYS[1])
return {current, ttl}
"""


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


def _error_response(status_code: int, code: str, message: str, *, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"data": None, "error": {"code": code, "message": message, "details": details}, "meta": {}},
    )


class RequestSecurityMiddleware:
    def __init__(self, app, settings: Settings):
        self.app = app
        self.settings = settings
        self._redis: Redis | None = None
        self._memory_lock = asyncio.Lock()
        self._memory_windows: dict[str, tuple[int, float]] = {}

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        rejection = await self._guard(request)
        if rejection is not None:
            await rejection(scope, receive, send)
            return
        await self.app(scope, receive, send)

    async def _guard(self, request: Request) -> JSONResponse | None:
        csrf_rejection = self._check_csrf(request)
        if csrf_rejection is not None:
            return csrf_rejection
        if not self.settings.rate_limit_enabled or not request.url.path.startswith(self.settings.api_prefix):
            return None

        limit = self._limit_for_request(request)
        result = await self._consume_rate_limit(request, limit)
        if result.allowed:
            return None
        return _error_response(
            429,
            "rate_limit_exceeded",
            "Too many requests. Please retry later.",
            details={"limit": result.limit, "retry_after_seconds": result.retry_after},
        )

    def _check_csrf(self, request: Request) -> JSONResponse | None:
        if not self.settings.csrf_enabled or request.method.upper() not in UNSAFE_METHODS:
            return None

        origin = str(request.headers.get("origin") or "").rstrip("/")
        trusted_origins = {item.rstrip("/") for item in self.settings.cors_origins}
        if origin and origin not in trusted_origins:
            return _error_response(403, "origin_forbidden", "Request origin is not allowed")

        has_auth_cookie = bool(
            request.cookies.get(self.settings.access_cookie_name)
            or request.cookies.get(self.settings.refresh_cookie_name)
        )
        if self.settings.is_production and has_auth_cookie and not origin:
            return _error_response(403, "origin_required", "Authenticated browser requests must include an Origin header")
        if not has_auth_cookie or request.url.path in CSRF_TOKEN_EXEMPT_PATHS:
            return None

        cookie_token = request.cookies.get(self.settings.csrf_cookie_name)
        header_token = request.headers.get(self.settings.csrf_header_name)
        if not cookie_token or not header_token or not hmac.compare_digest(cookie_token, header_token):
            return _error_response(403, "csrf_validation_failed", "CSRF token validation failed")
        return None

    def _limit_for_request(self, request: Request) -> int:
        path = request.url.path
        if path.startswith(f"{self.settings.api_prefix}/auth/"):
            return self.settings.rate_limit_auth_requests
        expensive_markers = ("/generate", "/refine", "/search", "/llm/", "/images/generate", "/exports")
        if any(marker in path for marker in expensive_markers):
            return self.settings.rate_limit_expensive_requests
        return self.settings.rate_limit_default_requests

    def _rate_limit_key(self, request: Request, limit: int) -> str:
        access_token = request.cookies.get(self.settings.access_cookie_name)
        client_host = request.client.host if request.client else "unknown"
        identity_source = access_token or client_host
        identity = hashlib.sha256(identity_source.encode("utf-8")).hexdigest()[:24]
        route = request.scope.get("route")
        route_path = getattr(route, "path", None) or request.url.path
        route_hash = hashlib.sha256(f"{request.method}:{route_path}:{limit}".encode("utf-8")).hexdigest()[:20]
        return f"travelmind:rate-limit:{route_hash}:{identity}"

    async def _consume_rate_limit(self, request: Request, limit: int) -> RateLimitResult:
        key = self._rate_limit_key(request, limit)
        if self.settings.rate_limit_backend == "redis":
            try:
                if self._redis is None:
                    self._redis = Redis.from_url(self.settings.redis_url, encoding="utf-8", decode_responses=True)
                current, ttl = await self._redis.eval(
                    RATE_LIMIT_SCRIPT,
                    1,
                    key,
                    self.settings.rate_limit_window_seconds,
                )
                current_value = int(current)
                retry_after = max(int(ttl), 1)
                return RateLimitResult(
                    allowed=current_value <= limit,
                    limit=limit,
                    remaining=max(limit - current_value, 0),
                    retry_after=retry_after,
                )
            except Exception:
                if self.settings.is_production:
                    return RateLimitResult(allowed=False, limit=limit, remaining=0, retry_after=5)
        return await self._consume_memory(key, limit)

    async def _consume_memory(self, key: str, limit: int) -> RateLimitResult:
        now = time.monotonic()
        window = max(self.settings.rate_limit_window_seconds, 1)
        async with self._memory_lock:
            count, expires_at = self._memory_windows.get(key, (0, now + window))
            if expires_at <= now:
                count, expires_at = 0, now + window
            count += 1
            self._memory_windows[key] = (count, expires_at)
            if len(self._memory_windows) > 4096:
                self._memory_windows = {
                    item_key: value for item_key, value in self._memory_windows.items() if value[1] > now
                }
        return RateLimitResult(
            allowed=count <= limit,
            limit=limit,
            remaining=max(limit - count, 0),
            retry_after=max(int(expires_at - now), 1),
        )
