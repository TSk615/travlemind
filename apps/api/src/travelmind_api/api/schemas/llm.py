from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LlmProxyRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=4096)
    wire_api: str | None = Field(default=None, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)