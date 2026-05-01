from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from travelmind_api.api.schemas.jobs import JobResponse


class ImageAssetResponse(BaseModel):
    id: str
    url: str
    path: str | None = None
    filename: str | None = None
    mime_type: str | None = None


class ImageGenerationRecordResponse(BaseModel):
    id: str
    user_id: str
    title: str
    destination: str
    scene_prompt: str
    mode: str
    status: str
    visibility: str
    prompt: str
    optimized_prompt: str | None = None
    negative_prompt: str | None = None
    style_tags: list[str] = Field(default_factory=list)
    source_images: list[ImageAssetResponse] = Field(default_factory=list)
    reference_images: list[ImageAssetResponse] = Field(default_factory=list)
    result_images: list[ImageAssetResponse] = Field(default_factory=list)
    provider: str | None = None
    model: str | None = None
    remix_from_id: str | None = None
    remix_count: int = 0
    published_at: datetime | None = None
    author_name: str | None = None
    created_at: datetime
    updated_at: datetime


class ImagePromptComposeRequest(BaseModel):
    title: str = ""
    destination: str = ""
    scene_prompt: str = ""
    prompt: str = ""
    negative_prompt: str = ""
    style_tags: list[str] = Field(default_factory=list)
    reference_urls: list[str] = Field(default_factory=list)
    reference_count: int = Field(default=0, ge=0)


class ImagePromptComposeResponse(BaseModel):
    title: str
    optimized_prompt: str
    negative_prompt: str


class ImageGenerationUpdateRequest(BaseModel):
    title: str | None = None
    destination: str | None = None
    style_tags: list[str] | None = None
    visibility: str | None = None

    @field_validator("title", "destination", "visibility", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        return str(value).strip()


class ImageGenerationStartResponse(BaseModel):
    generation: ImageGenerationRecordResponse
    job: JobResponse


class PromptTrendItemResponse(BaseModel):
    platform: str
    title: str
    prompt: str
    tags: list[str] = Field(default_factory=list)
    source_url: str | None = None


class PromptTrendResponse(BaseModel):
    items: list[PromptTrendItemResponse] = Field(default_factory=list)
    implemented: bool = False
    source: str = "reserved"
    platform: str
