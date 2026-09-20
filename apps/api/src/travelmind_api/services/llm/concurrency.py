from __future__ import annotations

import hashlib
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from threading import Lock
from typing import Protocol

from redis import Redis
from redis.exceptions import LockError

from travelmind_api.core.config import Settings


EndpointIdentity = tuple[str, str, str]
CancellationCheck = Callable[[], None]


class EndpointConcurrencyTimeout(RuntimeError):
    """Raised when a model endpoint remains occupied beyond its request budget."""


class EndpointConcurrencyLimiter(Protocol):
    def acquire(
        self,
        identity: EndpointIdentity,
        *,
        timeout_seconds: float,
        cancellation_check: CancellationCheck | None = None,
    ) -> AbstractContextManager[None]:
        ...


def _identity_digest(identity: EndpointIdentity) -> str:
    """Build a stable lock key without exposing endpoint credentials."""

    payload = "\0".join(str(part or "").strip().casefold() for part in identity)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class InProcessEndpointConcurrencyLimiter:
    """Serialize matching endpoints across every workflow in one process."""

    _registry_guard = Lock()
    _registry: dict[str, Lock] = {}

    @classmethod
    def _lock_for(cls, identity: EndpointIdentity) -> Lock:
        key = _identity_digest(identity)
        with cls._registry_guard:
            return cls._registry.setdefault(key, Lock())

    @contextmanager
    def acquire(
        self,
        identity: EndpointIdentity,
        *,
        timeout_seconds: float,
        cancellation_check: CancellationCheck | None = None,
    ) -> Iterator[None]:
        lock = self._lock_for(identity)
        deadline = time.monotonic() + max(float(timeout_seconds), 0.01)
        acquired = False
        while not acquired:
            if cancellation_check is not None:
                cancellation_check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EndpointConcurrencyTimeout("Timed out waiting for the model endpoint concurrency slot")
            acquired = lock.acquire(timeout=min(1.0, remaining))
        try:
            if cancellation_check is not None:
                cancellation_check()
            yield
        finally:
            lock.release()


class RedisEndpointConcurrencyLimiter:
    """Serialize matching endpoints across ARQ worker processes via Redis."""

    def __init__(self, redis_url: str, *, client: Redis | None = None) -> None:
        self._client = client or Redis.from_url(redis_url)

    @contextmanager
    def acquire(
        self,
        identity: EndpointIdentity,
        *,
        timeout_seconds: float,
        cancellation_check: CancellationCheck | None = None,
    ) -> Iterator[None]:
        wait_budget = max(float(timeout_seconds), 0.01)
        deadline = time.monotonic() + wait_budget
        lock = self._client.lock(
            f"travelmind:llm-endpoint:{_identity_digest(identity)}",
            timeout=wait_budget + 30.0,
        )
        acquired = False
        while not acquired:
            if cancellation_check is not None:
                cancellation_check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EndpointConcurrencyTimeout("Timed out waiting for the shared model endpoint concurrency slot")
            acquired = bool(
                lock.acquire(
                    blocking=True,
                    blocking_timeout=min(1.0, remaining),
                )
            )
        try:
            if cancellation_check is not None:
                cancellation_check()
            yield
        finally:
            try:
                lock.release()
            except LockError as exc:
                raise RuntimeError("Lost ownership of the shared model endpoint concurrency slot") from exc


def build_endpoint_concurrency_limiter(settings: Settings) -> EndpointConcurrencyLimiter:
    if settings.is_production or str(settings.queue_mode or "").strip().lower() == "arq":
        return RedisEndpointConcurrencyLimiter(settings.redis_url)
    return InProcessEndpointConcurrencyLimiter()
