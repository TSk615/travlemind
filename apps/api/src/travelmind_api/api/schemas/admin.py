from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator


class AdminActionRequest(BaseModel):
    reason: str = Field(min_length=2, max_length=500)

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 2:
            raise ValueError("reason must contain at least 2 non-space characters")
        return normalized


class AdminPageResponse(BaseModel):
    items: list[Any]
    page: int
    page_size: int
    total: int


class AdminUserSummary(BaseModel):
    id: str
    email: str
    name: str
    avatar: str | None = None
    locale: str
    created_at: datetime
    is_admin: bool
    disabled_at: datetime | None = None
    disabled_reason: str | None = None
    trip_count: int = 0
    community_post_count: int = 0
    job_count: int = 0


class AdminUserDetail(AdminUserSummary):
    xhs_source_enabled: bool = False
    has_llm_api_key: bool = False
    has_search_api_key: bool = False
    has_image_api_key: bool = False


class AdminOwnerSummary(BaseModel):
    id: str
    email: str
    name: str
    is_admin: bool
    disabled_at: datetime | None = None


class AdminTripSummary(BaseModel):
    id: str
    user_id: str
    owner: AdminOwnerSummary | None = None
    title: str
    origin: str
    destination: str
    start_date: date
    end_date: date
    budget: float
    travelers: int
    created_at: datetime
    updated_at: datetime
    has_itinerary: bool
    has_community_post: bool


class AdminTripDetail(AdminTripSummary):
    interests: list[str] = Field(default_factory=list)
    accommodation_preference: str
    pace: str
    transport_mode: str
    itinerary: dict[str, Any] | None = None
    latest_agent_trace: dict[str, Any] | None = None


class AdminCommunityPostSummary(BaseModel):
    id: str
    trip_id: str
    author_user_id: str
    author: AdminOwnerSummary | None = None
    title: str
    destination: str
    share_note: str
    cover_image_url: str | None = None
    published_at: datetime
    updated_at: datetime
    source_trip_updated_at: datetime
    is_stale: bool


class AdminCommunityPostDetail(AdminCommunityPostSummary):
    snapshot: dict[str, Any]


class AdminJobSummary(BaseModel):
    job_id: str
    owner_user_id: str | None = None
    owner: AdminOwnerSummary | None = None
    status: str
    type: str
    trip_id: str | None = None
    created_at: datetime
    updated_at: datetime
    stage: str | None = None
    stage_message: str | None = None
    progress_percent: int | None = None
    error_message: str | None = None


class AdminJobDetail(AdminJobSummary):
    timeline_json: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    payload: dict[str, Any] | None = None
