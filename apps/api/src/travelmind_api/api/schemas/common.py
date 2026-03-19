from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ErrorPayload(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class Envelope(BaseModel):
    data: Any = None
    error: ErrorPayload | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


def success_response(data: Any, *, meta: dict[str, Any] | None = None) -> Envelope:
    return Envelope(data=data, error=None, meta=meta or {})
