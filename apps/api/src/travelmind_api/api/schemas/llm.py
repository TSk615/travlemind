from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LlmProxyRequest(BaseModel):
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(min_length=1, max_length=4096)
    wire_api: str = Field(default="responses", min_length=1, max_length=64)
    payload: dict[str, Any] = Field(default_factory=dict)