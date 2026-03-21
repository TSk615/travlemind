from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, Field

WireApi = Literal["chat_completions", "responses"]


def normalize_wire_api(value: object | None, *, default: WireApi = "chat_completions") -> WireApi:
    candidate = str(value or "").strip().lower()
    if candidate in {"responses", "response"}:
        return "responses"
    if candidate in {"chat_completions", "chat/completions", "chat-completions", "chat"}:
        return "chat_completions"
    return default


class LlmConfig(BaseModel):
    base_url: str
    api_key: str
    model: str
    wire_api: WireApi = "chat_completions"
    timeout_seconds: float = Field(default=30.0, gt=0)

    @property
    def endpoint_url(self) -> str:
        normalized_base = self.base_url.rstrip("/")
        if self.wire_api == "responses":
            if normalized_base.endswith("/responses"):
                return normalized_base
            return f"{normalized_base}/responses"

        if normalized_base.endswith("/chat/completions"):
            return normalized_base
        return f"{normalized_base}/chat/completions"

    @classmethod
    def from_env(cls) -> LlmConfig | None:
        base_url = (os.getenv("TRAVELMIND_LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "").strip()
        api_key = (os.getenv("TRAVELMIND_LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        model = (os.getenv("TRAVELMIND_LLM_MODEL") or os.getenv("OPENAI_MODEL") or "").strip()
        wire_api = normalize_wire_api(os.getenv("TRAVELMIND_LLM_WIRE_API") or os.getenv("OPENAI_WIRE_API"), default="chat_completions")
        timeout_raw = (os.getenv("TRAVELMIND_LLM_TIMEOUT_SECONDS") or "30").strip()
        if not base_url or not api_key or not model:
            return None
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            timeout_seconds = 30.0
        return cls(
            base_url=base_url.rstrip("/"),
            api_key=api_key,
            model=model,
            wire_api=wire_api,
            timeout_seconds=timeout_seconds,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> LlmConfig | None:
        if payload is None:
            return None

        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        api_key = str(payload.get("api_key") or "").strip()
        model = str(payload.get("model") or "").strip()
        wire_api = normalize_wire_api(payload.get("wire_api"), default="responses")
        timeout_raw = str(payload.get("timeout_seconds") or "30").strip()
        if not base_url or not api_key or not model:
            return None

        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            timeout_seconds = 30.0

        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            wire_api=wire_api,
            timeout_seconds=timeout_seconds,
        )