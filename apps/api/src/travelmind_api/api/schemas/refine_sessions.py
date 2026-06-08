from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


def _strip_text(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("value cannot be empty")
    return normalized


class TripRefineMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    text: str
    created_at: datetime


class TripUploadedGuideSource(BaseModel):
    id: str
    title: str
    content: str
    source_type: str = "manual_text"
    original_filename: str | None = None
    created_at: datetime


class TripCommunityGuideSource(BaseModel):
    id: str
    post_id: str
    title: str
    destination: str
    author_name: str
    share_note: str
    itinerary_summary: str
    snapshot: dict[str, Any]
    created_at: datetime


class TripRefineSessionResponse(BaseModel):
    id: str
    trip_id: str
    messages: list[TripRefineMessage] = Field(default_factory=list)
    uploaded_guides: list[TripUploadedGuideSource] = Field(default_factory=list)
    community_sources: list[TripCommunityGuideSource] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class TripRefineMessageCreateRequest(BaseModel):
    role: Literal["user", "assistant"]
    text: str = Field(min_length=1, max_length=8000)

    @field_validator("text")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        return _strip_text(value)


class TripUploadedGuideCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    content: str = Field(min_length=20, max_length=40000)
    source_type: str = Field(default="manual_text", min_length=2, max_length=64)
    original_filename: str | None = Field(default=None, max_length=255)

    @field_validator("title", "content", "source_type")
    @classmethod
    def _normalize_required_text(cls, value: str) -> str:
        return _strip_text(value)

    @field_validator("original_filename")
    @classmethod
    def _normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class TripCommunityGuideAttachRequest(BaseModel):
    post_id: str = Field(min_length=3, max_length=32)

    @field_validator("post_id")
    @classmethod
    def _normalize_post_id(cls, value: str) -> str:
        return _strip_text(value)
