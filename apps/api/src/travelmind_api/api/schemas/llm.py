from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LlmProxyRequest(BaseModel):
    provider_protocol: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    wire_api: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)


class LlmModelsRequest(BaseModel):
    provider_protocol: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)


class LlmConnectionTestRequest(BaseModel):
    provider_protocol: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    model: str | None = Field(default=None, max_length=255)
    wire_api: str | None = Field(default=None, max_length=64)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)


class LlmConnectionTestResponse(BaseModel):
    provider_protocol: str
    base_url: str
    model: str
    wire_api: str
    ok: bool
    reply: str
    latency_ms: int
