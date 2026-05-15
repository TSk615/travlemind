from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pydantic import BaseModel, Field

from travelmind_api.core.env import get_env

_LOGGER = logging.getLogger(__name__)

_SEARCH_CACHE: dict[str, tuple[float, list["XhsCrawlerPost"]]] = {}


@dataclass(frozen=True)
class XhsCrawlerConfig:
    base_url: str
    api_key: str | None = None
    timeout_seconds: float = 20.0
    cache_ttl_seconds: int = 1800
    limit_per_query: int = 5
    max_results: int = 10

    @classmethod
    def from_env(cls) -> XhsCrawlerConfig | None:
        enabled = str(get_env("TRAVELMIND_XHS_CRAWLER_ENABLED") or "").strip().lower()
        if enabled not in {"1", "true", "yes", "on"}:
            return None

        base_url = str(get_env("TRAVELMIND_XHS_CRAWLER_BASE_URL") or "").strip().rstrip("/")
        if not base_url:
            return None

        api_key = str(get_env("TRAVELMIND_XHS_CRAWLER_API_KEY") or "").strip() or None
        timeout_seconds = _coerce_float(get_env("TRAVELMIND_XHS_CRAWLER_TIMEOUT_SECONDS"), default=20.0)
        cache_ttl_seconds = _coerce_int(get_env("TRAVELMIND_XHS_CACHE_TTL_SECONDS"), default=1800)
        limit_per_query = _coerce_int(get_env("TRAVELMIND_XHS_LIMIT_PER_QUERY"), default=5)
        max_results = _coerce_int(get_env("TRAVELMIND_XHS_MAX_RESULTS"), default=10)
        return cls(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=max(timeout_seconds, 1.0),
            cache_ttl_seconds=max(cache_ttl_seconds, 0),
            limit_per_query=max(limit_per_query, 1),
            max_results=max(max_results, 1),
        )


class XhsCrawlerPost(BaseModel):
    post_id: str
    title: str = ""
    url: str
    author: str = ""
    published_at: str | None = None
    excerpt: str = ""
    engagement_hint: str | None = None
    tags: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    raw_destination_hint: str | None = None


class XhsCrawlerBindingState(BaseModel):
    bind_id: str
    status: str
    verification_url: str | None = None
    verification_code: str | None = None
    qr_image_data_url: str | None = None
    expires_at: str | None = None
    completed_at: str | None = None
    message: str | None = None
    xhs_user_id: str | None = None
    display_name: str | None = None
    session_payload: dict[str, Any] | None = None
    session_expires_at: str | None = None


class XhsCrawlerClientError(RuntimeError):
    pass


class XhsCrawlerSessionExpiredError(XhsCrawlerClientError):
    pass


class XhsCrawlerClient:
    def __init__(self, config: XhsCrawlerConfig, *, http_client: httpx.Client | None = None) -> None:
        self._config = config
        self._http_client = http_client

    def start_binding(self, *, user_id: str) -> XhsCrawlerBindingState:
        body = self._post_json("/internal/xhs/bind/start", {"user_id": str(user_id).strip()})
        return XhsCrawlerBindingState.model_validate(body)

    def get_binding(self, *, bind_id: str) -> XhsCrawlerBindingState:
        body = self._get_json(f"/internal/xhs/bind/{bind_id}")
        return XhsCrawlerBindingState.model_validate(body)

    def delete_session(self, *, user_id: str) -> None:
        self._delete_json(f"/internal/xhs/session/{user_id}")

    def search_posts(
        self,
        *,
        user_id: str,
        session_payload: dict[str, Any],
        destination: str,
        queries: list[str],
        limit_per_query: int | None = None,
    ) -> list[XhsCrawlerPost]:
        normalized_user_id = str(user_id or "").strip()
        normalized_destination = str(destination or "").strip()
        normalized_queries = [str(item or "").strip() for item in queries if str(item or "").strip()]
        if not normalized_user_id or not normalized_destination or not normalized_queries or not isinstance(session_payload, dict):
            return []

        effective_limit = max(int(limit_per_query or self._config.limit_per_query), 1)
        cache_key = self._cache_key(normalized_user_id, normalized_destination, normalized_queries, effective_limit)
        cached = self._cached_posts(cache_key)
        if cached is not None:
            return [post.model_copy(deep=True) for post in cached]

        payload = {
            "user_id": normalized_user_id,
            "destination": normalized_destination,
            "queries": normalized_queries,
            "limit_per_query": effective_limit,
            "session_payload": session_payload,
        }
        body = self._post_json("/internal/xhs/session/search", payload)
        raw_posts = body.get("posts") if isinstance(body, dict) else None
        if not isinstance(raw_posts, list):
            raise XhsCrawlerClientError("XHS crawler response missing posts array")

        posts: list[XhsCrawlerPost] = []
        seen: set[str] = set()
        for item in raw_posts:
            if not isinstance(item, dict):
                continue
            post = XhsCrawlerPost.model_validate(item)
            dedupe_key = post.post_id.strip() or post.url.strip().lower()
            if dedupe_key in seen or post.url.strip().lower() in seen:
                continue
            seen.add(dedupe_key)
            seen.add(post.url.strip().lower())
            posts.append(post)
            if len(posts) >= self._config.max_results:
                break

        self._store_cache(cache_key, posts)
        return [post.model_copy(deep=True) for post in posts]

    def search_posts_debug(
        self,
        *,
        user_id: str,
        session_payload: dict[str, Any],
        destination: str,
        queries: list[str],
        limit_per_query: int | None = None,
    ) -> dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        normalized_destination = str(destination or "").strip()
        normalized_queries = [str(item or "").strip() for item in queries if str(item or "").strip()]
        if not normalized_user_id or not normalized_destination or not normalized_queries or not isinstance(session_payload, dict):
            return {
                "destination": normalized_destination,
                "queries": normalized_queries,
                "limit_per_query": max(int(limit_per_query or self._config.limit_per_query), 1),
                "record_count": 0,
                "post_count": 0,
                "posts": [],
                "records": [],
            }

        payload = {
            "user_id": normalized_user_id,
            "destination": normalized_destination,
            "queries": normalized_queries,
            "limit_per_query": max(int(limit_per_query or self._config.limit_per_query), 1),
            "session_payload": session_payload,
        }
        body = self._post_json("/internal/xhs/session/search-debug", payload)
        if not isinstance(body, dict):
            raise XhsCrawlerClientError("XHS crawler debug response root must be an object")
        return body

    def _cache_key(self, user_id: str, destination: str, queries: list[str], limit_per_query: int) -> str:
        joined_queries = "|".join(query.casefold() for query in queries)
        return f"{self._config.base_url}|{user_id}|{destination.casefold()}|{joined_queries}|{limit_per_query}|{self._config.max_results}"

    def _cached_posts(self, cache_key: str) -> list[XhsCrawlerPost] | None:
        if self._config.cache_ttl_seconds <= 0:
            return None
        cached = _SEARCH_CACHE.get(cache_key)
        if cached is None:
            return None
        expires_at, posts = cached
        if expires_at < time.time():
            _SEARCH_CACHE.pop(cache_key, None)
            return None
        return posts

    def _store_cache(self, cache_key: str, posts: list[XhsCrawlerPost]) -> None:
        if self._config.cache_ttl_seconds <= 0:
            return
        _SEARCH_CACHE[cache_key] = (time.time() + self._config.cache_ttl_seconds, [post.model_copy(deep=True) for post in posts])

    def _post_json(self, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", endpoint, json=payload)

    def _get_json(self, endpoint: str) -> dict[str, Any]:
        return self._request_json("GET", endpoint)

    def _delete_json(self, endpoint: str) -> dict[str, Any]:
        return self._request_json("DELETE", endpoint)

    def _request_json(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self._config.base_url}{endpoint}"
        headers = {"Content-Type": "application/json"}
        if self._config.api_key:
            headers["Authorization"] = f"Bearer {self._config.api_key}"

        try:
            if self._http_client is not None:
                response = self._http_client.request(method, url, headers=headers, **kwargs)
            else:
                with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=True) as client:
                    response = client.request(method, url, headers=headers, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = _extract_error_detail(exc.response)
            code = detail.get("code")
            if code == "xhs_session_expired":
                raise XhsCrawlerSessionExpiredError(detail.get("message") or "XHS session expired") from exc
            raise XhsCrawlerClientError(f"XHS crawler request failed: {detail.get('message') or exc.response.text[:300]}") from exc
        except httpx.HTTPError as exc:
            raise XhsCrawlerClientError(f"XHS crawler request failed: {exc}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            raise XhsCrawlerClientError(f"XHS crawler returned non-JSON body: {response.text[:300]}") from exc
        if not isinstance(body, dict):
            raise XhsCrawlerClientError("XHS crawler response root must be an object")
        return body


def _extract_error_detail(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {"code": "xhs_crawler_failed", "message": response.text[:300]}
    if isinstance(body, dict) and isinstance(body.get("detail"), dict):
        return body["detail"]
    if isinstance(body, dict):
        return body
    return {"code": "xhs_crawler_failed", "message": response.text[:300]}


def _coerce_float(value: object | None, *, default: float) -> float:
    try:
        return float(str(value or "").strip())
    except (TypeError, ValueError):
        return default


def _coerce_int(value: object | None, *, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return default
