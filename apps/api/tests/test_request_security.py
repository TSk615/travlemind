from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from travelmind_api.core.config import Settings
from travelmind_api.core.request_security import RequestSecurityMiddleware


def _security_app(**overrides) -> FastAPI:
    values = {
        "environment": "test",
        "cors_origins": ["http://trusted.example"],
        "csrf_enabled": True,
        "rate_limit_enabled": True,
        "rate_limit_backend": "memory",
        "rate_limit_window_seconds": 60,
        "rate_limit_default_requests": 2,
    }
    values.update(overrides)
    settings = Settings(**values)
    app = FastAPI()
    app.add_middleware(RequestSecurityMiddleware, settings=settings)

    @app.post("/api/v1/protected")
    def protected():
        return {"ok": True}

    @app.get("/api/v1/read")
    def read():
        return {"ok": True}

    return app


def test_csrf_rejects_untrusted_origins_and_mismatched_tokens():
    with TestClient(_security_app(rate_limit_enabled=False)) as client:
        client.cookies.set("travelmind_access", "access-token")
        client.cookies.set("travelmind_csrf", "csrf-token")

        untrusted = client.post("/api/v1/protected", headers={"Origin": "http://evil.example", "X-CSRF-Token": "csrf-token"})
        missing = client.post("/api/v1/protected", headers={"Origin": "http://trusted.example"})
        accepted = client.post(
            "/api/v1/protected",
            headers={"Origin": "http://trusted.example", "X-CSRF-Token": "csrf-token"},
        )

    assert untrusted.status_code == 403
    assert untrusted.json()["error"]["code"] == "origin_forbidden"
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "csrf_validation_failed"
    assert accepted.status_code == 200


def test_memory_rate_limit_rejects_requests_after_the_limit():
    with TestClient(_security_app(csrf_enabled=False)) as client:
        assert client.get("/api/v1/read").status_code == 200
        assert client.get("/api/v1/read").status_code == 200
        limited = client.get("/api/v1/read")

    assert limited.status_code == 429
    assert limited.json()["error"]["code"] == "rate_limit_exceeded"
