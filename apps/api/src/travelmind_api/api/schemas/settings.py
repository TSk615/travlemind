from __future__ import annotations

from pydantic import BaseModel, Field


class LlmSettingsUpdateRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=255)
    wire_api: str | None = Field(default=None, max_length=64)


class LlmSettingsResponse(BaseModel):
    base_url: str | None = None
    api_key_masked: str | None = None
    has_api_key: bool = False
    model: str | None = None
    wire_api: str | None = None
    configured: bool = False