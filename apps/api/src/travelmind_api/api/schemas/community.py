from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from travelmind_api.api.schemas.trips import AgentRunTrace, GeneratedItinerary


def _normalize_share_note(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


class CommunityTripSnapshot(BaseModel):
    title: str
    origin: str
    destination: str
    start_date: date
    end_date: date
    budget: float
    travelers: int
    interests: list[str] = Field(default_factory=list)
    accommodation_preference: str
    pace: str
    transport_mode: str
    itinerary: GeneratedItinerary
    latest_agent_trace: AgentRunTrace | None = None


class CommunityPostSummary(BaseModel):
    id: str
    title: str
    destination: str
    share_note: str
    cover_image_url: str | None = None
    author_name: str
    published_at: datetime
    updated_at: datetime
    start_date: date
    end_date: date
    budget: float
    travelers: int
    interests: list[str] = Field(default_factory=list)
    itinerary_summary: str
    day_count: int


class CommunityPostDetail(BaseModel):
    id: str
    title: str
    destination: str
    share_note: str
    cover_image_url: str | None = None
    author_name: str
    published_at: datetime
    updated_at: datetime
    snapshot: CommunityTripSnapshot


class CommunityPostCreateRequest(BaseModel):
    trip_id: str = Field(min_length=3, max_length=32)
    share_note: str = Field(default="", max_length=280)

    @field_validator("trip_id")
    @classmethod
    def _strip_trip_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("trip_id cannot be empty")
        return normalized

    @field_validator("share_note")
    @classmethod
    def _strip_share_note(cls, value: str) -> str:
        return _normalize_share_note(value) or ""


class CommunityPostUpdateRequest(BaseModel):
    share_note: str = Field(default="", max_length=280)

    @field_validator("share_note")
    @classmethod
    def _strip_share_note(cls, value: str) -> str:
        return _normalize_share_note(value) or ""


class CommunityPostRefreshRequest(BaseModel):
    share_note: str | None = Field(default=None, max_length=280)

    @field_validator("share_note")
    @classmethod
    def _strip_share_note(cls, value: str | None) -> str | None:
        return _normalize_share_note(value)
