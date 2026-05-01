from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class XhsSearchPost(BaseModel):
    post_id: str
    title: str = ""
    url: str
    author: str = ""
    published_at: str | None = None
    excerpt: str = ""
    engagement_hint: str | None = None
    tags: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    raw_destination_hint: str | None = None


class XhsSearchResponse(BaseModel):
    posts: list[XhsSearchPost] = Field(default_factory=list)


class InternalXhsBindStartRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)


class InternalXhsBindingState(BaseModel):
    bind_id: str
    status: str
    verification_url: str | None = None
    verification_code: str | None = None
    qr_image_data_url: str | None = None
    expires_at: str | None = None
    completed_at: str | None = None
    message: str | None = None
    xhs_user_id: str | None = None
    display_name: str | None = None
    session_payload: dict[str, Any] | None = None
    session_expires_at: str | None = None


class InternalXhsSessionSearchRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)
    destination: str = Field(min_length=1, max_length=255)
    queries: list[str] = Field(min_length=1, max_length=4)
    limit_per_query: int = Field(default=5, ge=1, le=10)
    session_payload: dict[str, Any]
