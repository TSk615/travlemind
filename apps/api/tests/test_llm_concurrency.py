from __future__ import annotations

import pytest

from travelmind_api.core.config import Settings
from travelmind_api.services.llm.concurrency import (
    EndpointConcurrencyTimeout,
    InProcessEndpointConcurrencyLimiter,
    RedisEndpointConcurrencyLimiter,
    build_endpoint_concurrency_limiter,
)


def test_in_process_limiter_is_shared_across_instances_and_scoped_by_endpoint():
    first = InProcessEndpointConcurrencyLimiter()
    second = InProcessEndpointConcurrencyLimiter()
    identity = ("newapi", "https://llm.example.test/v1", "secret-key")

    with first.acquire(identity, timeout_seconds=0.1):
        with second.acquire(("newapi", "https://other.example.test/v1", "secret-key"), timeout_seconds=0.1):
            pass
        with pytest.raises(EndpointConcurrencyTimeout):
            with second.acquire(identity, timeout_seconds=0.02):
                pass


def test_in_process_limiter_checks_cancellation_before_waiting():
    limiter = InProcessEndpointConcurrencyLimiter()

    def cancelled() -> None:
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        with limiter.acquire(("openai", "https://llm.example.test/v1", "key"), timeout_seconds=1, cancellation_check=cancelled):
            pass


def test_redis_limiter_uses_hashed_key_and_releases_lock():
    calls: list[tuple[str, object]] = []

    class FakeLock:
        def acquire(self, **kwargs):
            calls.append(("acquire", kwargs))
            return True

        def release(self):
            calls.append(("release", None))

    class FakeRedis:
        def lock(self, name, **kwargs):
            calls.append((name, kwargs))
            return FakeLock()

    secret = "never-include-this-secret"
    limiter = RedisEndpointConcurrencyLimiter("redis://unused", client=FakeRedis())
    with limiter.acquire(("newapi", "https://llm.example.test/v1", secret), timeout_seconds=5):
        pass

    lock_name = calls[0][0]
    assert lock_name.startswith("travelmind:llm-endpoint:")
    assert secret not in lock_name
    assert calls[-1] == ("release", None)


def test_limiter_factory_uses_redis_for_arq_and_process_lock_for_inline():
    assert isinstance(
        build_endpoint_concurrency_limiter(Settings(queue_mode="inline")),
        InProcessEndpointConcurrencyLimiter,
    )
    assert isinstance(
        build_endpoint_concurrency_limiter(Settings(queue_mode="arq")),
        RedisEndpointConcurrencyLimiter,
    )
    production = Settings(
        environment="production",
        queue_mode="inline",
        jwt_secret="jwt-production-secret-with-at-least-32-characters",
        credential_encryption_key="credential-production-secret-at-least-32-characters",
        database_url="postgresql+psycopg://travelmind:secret@db.example/travelmind",
        public_api_url="https://api.travelmind.example",
        cors_origins=["https://travelmind.example"],
        upstream_private_url_policy="deny",
        rate_limit_backend="redis",
    )
    assert isinstance(build_endpoint_concurrency_limiter(production), RedisEndpointConcurrencyLimiter)
