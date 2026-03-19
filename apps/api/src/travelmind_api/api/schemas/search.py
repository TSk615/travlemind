from __future__ import annotations

from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    trust_score: float
    quality_score: float
    freshness_score: float
    ad_score: float
    final_score: float
    reasons: list[str]


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=255)
    destination: str | None = None
    manual_links: list[str] = Field(default_factory=list)


class SearchGeoPoint(BaseModel):
    lat: float
    lng: float


class SearchDocumentResponse(BaseModel):
    id: str
    platform: str
    title: str
    url: str
    summary: str
    destination: str | None = None
    place_name: str | None = None
    category: str | None = None
    opening_hours: str | None = None
    price_hint: str | None = None
    address: str | None = None
    geo: SearchGeoPoint | None = None
    source_type: str
    scores: ScoreBreakdown
