from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ExportPdfRequest(BaseModel):
    trip_id: str


class JobTimelineEntry(BaseModel):
    recorded_at: datetime
    status: str
    stage: str | None = None
    stage_message: str | None = None
    progress_percent: int | None = None


class JobResponse(BaseModel):
    job_id: str
    status: str
    type: str
    trip_id: str | None
    created_at: datetime
    updated_at: datetime
    stage: str | None = None
    stage_message: str | None = None
    progress_percent: int | None = None
    timeline_json: list[JobTimelineEntry] = Field(default_factory=list)
    result: dict[str, Any] | None = None
    error_message: str | None = None
