from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ExportPdfRequest(BaseModel):
    trip_id: str


class ExportRequest(BaseModel):
    trip_id: str
    formats: list[Literal["md", "pdf", "json"]] = Field(default_factory=lambda: ["md", "pdf", "json"])


class JobTimelineEntry(BaseModel):
    recorded_at: datetime
    status: str
    stage: str | None = None
    stage_message: str | None = None
    progress_percent: int | None = None
    attempt_count: int = 0
    max_attempts: int = 3


class JobResponse(BaseModel):
    job_id: str
    status: str
    type: str
    trip_id: str | None
    can_resume: bool = False
    resume_from_job_id: str | None = None
    resume_failed_role: str | None = None
    resume_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    stage: str | None = None
    stage_message: str | None = None
    progress_percent: int | None = None
    timeline_json: list[JobTimelineEntry] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error_message: str | None = None
    public_error_code: str | None = None
    quota_refunded: bool = False
