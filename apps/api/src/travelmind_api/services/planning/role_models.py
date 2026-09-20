from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Any, TypeVar
from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from travelmind_api.agents.base import BookingInfo, VisitRequirements
from travelmind_api.services.entity_identity import normalize_identity
from travelmind_api.services.planning_details import HotelEvidence, TransportLeg, TransportServiceCandidate


_LOGGER = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


class PlanningBrief(BaseModel):
    destination: str = Field(min_length=1)
    trip_days: int = Field(ge=1)
    budget_band: str = Field(default="")
    budget_is_hard_constraint: bool = True
    budget_priority: str = Field(default="")
    allow_budget_flex: bool = False
    pace: str = Field(default="")
    must_have: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    transport: str = Field(default="")
    accommodation: str = Field(default="")
    interests: list[str] = Field(default_factory=list)
    planning_constraints: list[str] = Field(default_factory=list)

    @field_validator("budget_is_hard_constraint", "allow_budget_flex", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "y", "required"}:
            return True
        if normalized in {"0", "false", "no", "n", "not_required"}:
            return False
        return False


class ResearchPoi(BaseModel):
    name: str = Field(min_length=1)
    kind: str = Field(default="attraction")
    area: str = Field(default="")
    category: str = Field(default="")
    highlights: list[str] = Field(default_factory=list)
    reason: str = Field(default="")
    suggested_time: str = Field(default="")
    confidence: str = Field(default="low")
    source_urls: list[str] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    booking_info: BookingInfo | None = None
    visit_requirements: VisitRequirements | None = None
    cuisine_or_type: str = Field(default="")
    price_hint: str = Field(default="unknown")
    price_checked_at: str = Field(default="unknown")
    price_valid_for: str = Field(default="")
    review_score: str = Field(default="unknown")
    review_count: str = Field(default="unknown")
    review_summary: str = Field(default="")
    signature_dishes: list[str] = Field(default_factory=list)
    reservation_hint: str = Field(default="")
    queue_hint: str = Field(default="")


class TopPoiItem(BaseModel):
    rank: int | None = None
    name: str = Field(default="")
    name_cn: str = Field(default="")
    name_en: str = Field(default="")
    kind: str = Field(default="")
    category: str = Field(default="")
    area: str = Field(default="")
    highlights: list[str] = Field(default_factory=list)
    reason: str = Field(default="")
    description: str = Field(default="")
    why_worth: str = Field(default="")
    suggested_time: str = Field(default="")
    tips: str = Field(default="")
    confidence: str = Field(default="")
    xhs_appeal: str = Field(default="")
    source_url: str = Field(default="")
    source_urls: list[str] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)


class AttractionGrounding(BaseModel):
    candidate_areas: list[str] = Field(default_factory=list)
    featured_pois: list[ResearchPoi] = Field(default_factory=list)
    sequencing_hints: list[str] = Field(default_factory=list)
    crowd_notes: list[str] = Field(default_factory=list)
    attraction_risks: list[str] = Field(default_factory=list)


class PoiGrounding(BaseModel):
    title: str = Field(default="")
    update: str = Field(default="")
    best_season: str = Field(default="")
    recommended_duration: str = Field(default="")
    general_tips: str = Field(default="")
    top_pois: list[TopPoiItem] = Field(default_factory=list)
    candidate_areas: list[str] = Field(default_factory=list)
    featured_pois: list[ResearchPoi] = Field(default_factory=list)
    sequencing_hints: list[str] = Field(default_factory=list)
    crowd_notes: list[str] = Field(default_factory=list)
    meal_strategy: list[str] = Field(default_factory=list)
    price_notes: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    poi_risks: list[str] = Field(default_factory=list)

    @field_validator("featured_pois", mode="before")
    @classmethod
    def _default_featured_pois(cls, value: Any) -> Any:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return cls._dedupe_raw_poi_items(value, name_keys=("name", "name_cn", "name_en"))
        return value

    @field_validator("top_pois", mode="before")
    @classmethod
    def _default_top_pois(cls, value: Any) -> Any:
        if value in (None, ""):
            return []
        if isinstance(value, list):
            return cls._dedupe_raw_poi_items(value, name_keys=("name_cn", "name_en", "name"))
        return value

    @classmethod
    def model_validate(cls, obj: Any, *args: Any, **kwargs: Any):  # type: ignore[override]
        instance = super().model_validate(obj, *args, **kwargs)
        cleaned_featured = [cls._sanitize_research_poi_sources(item) for item in cls._dedupe_research_pois(instance.featured_pois)]
        if cleaned_featured:
            return instance.model_copy(update={"featured_pois": cleaned_featured[:20]})
        cleaned_top_pois = [cls._sanitize_top_poi_sources(item) for item in cls._dedupe_top_pois(instance.top_pois)]
        if not cleaned_top_pois:
            return instance.model_copy(update={"featured_pois": [], "top_pois": []})
        mapped = cls._map_top_pois_to_featured_pois(cleaned_top_pois)
        return instance.model_copy(
            update={
                "top_pois": cleaned_top_pois[:20],
                "featured_pois": mapped["featured_pois"],
                "candidate_areas": instance.candidate_areas or mapped["candidate_areas"],
                "sequencing_hints": instance.sequencing_hints or mapped["sequencing_hints"],
                "crowd_notes": instance.crowd_notes or mapped["crowd_notes"],
                "poi_risks": instance.poi_risks or mapped["poi_risks"],
            }
        )

    @staticmethod
    def _poi_name_key(value: Any) -> str:
        normalized = re.sub(r"\s+", " ", str(value or "")).strip()
        if not normalized or len(normalized) > 56:
            return ""
        return normalized.casefold()

    @classmethod
    def _dedupe_raw_poi_items(cls, values: list[Any], *, name_keys: tuple[str, ...]) -> list[Any]:
        deduped: list[Any] = []
        seen: set[str] = set()
        for item in values:
            if isinstance(item, dict):
                raw_name = next((item.get(key) for key in name_keys if cls._poi_name_key(item.get(key))), "")
                key = cls._poi_name_key(raw_name)
                if not key or key in seen:
                    continue
                seen.add(key)
            deduped.append(item)
        return deduped[:20]

    @classmethod
    def _dedupe_top_pois(cls, top_pois: list[TopPoiItem]) -> list[TopPoiItem]:
        deduped: list[TopPoiItem] = []
        seen: set[str] = set()
        for item in top_pois:
            key = cls._poi_name_key(item.name or item.name_cn or item.name_en)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped[:20]

    @classmethod
    def _dedupe_research_pois(cls, pois: list[ResearchPoi]) -> list[ResearchPoi]:
        deduped: list[ResearchPoi] = []
        seen: set[str] = set()
        for poi in pois:
            key = cls._poi_name_key(poi.name)
            if not key or key in seen:
                continue
            seen.add(key)
            deduped.append(poi)
        return deduped[:20]

    @staticmethod
    def _is_generic_poi_source_url(value: str) -> bool:
        """Reject home/channel/search pages that cannot substantiate a specific POI."""
        try:
            parsed = urlparse(str(value or "").strip())
        except ValueError:
            return True
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return True
        host = parsed.netloc.casefold().split(":", 1)[0]
        if host.startswith("www."):
            host = host[4:]
        path = re.sub(r"/+", "/", parsed.path or "/").rstrip("/").casefold()
        if not path:
            return True
        generic_paths = {
            ("shantou.gov.cn", ""),
            ("ctrip.com", "/sight/shantou"),
            ("mafengwo.cn", "/poi"),
            ("xiaohongshu.com", "/explore"),
            ("zhihu.com", "/search"),
        }
        if (host, path) in generic_paths:
            return True
        if any(token in path for token in ("/search", "/searchresult", "/query")):
            return True
        if any(token in path for token in ("/hotels/", "/hotel/", "/restaurants/", "/restaurant/")):
            return True
        return False

    @classmethod
    def _clean_poi_source_urls(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            url = str(value or "").strip()
            if not url or cls._is_generic_poi_source_url(url) or url in cleaned:
                continue
            cleaned.append(url)
        return cleaned[:3]

    @classmethod
    def _sanitize_top_poi_sources(cls, item: TopPoiItem) -> TopPoiItem:
        candidates = [
            *([item.source_url] if str(item.source_url or "").strip() else []),
            *item.source_urls,
        ]
        cleaned = cls._clean_poi_source_urls(candidates)
        confidence = str(item.confidence or "").strip().lower()
        return item.model_copy(
            update={
                "source_url": cleaned[0] if cleaned else "",
                "source_urls": cleaned,
                "confidence": confidence if cleaned else "low",
            }
        )

    @classmethod
    def _sanitize_research_poi_sources(cls, item: ResearchPoi) -> ResearchPoi:
        cleaned = cls._clean_poi_source_urls(item.source_urls)
        return item.model_copy(update={"source_urls": cleaned, "confidence": item.confidence if cleaned else "low"})

    @classmethod
    def _map_top_pois_to_featured_pois(cls, top_pois: list[TopPoiItem]) -> dict[str, Any]:
        featured: list[ResearchPoi] = []
        candidate_areas: list[str] = []
        for item in top_pois:
            name = str(item.name or item.name_cn or item.name_en or "").strip()
            if not name:
                continue
            category = str(item.kind or item.category or "").strip()
            area = str(item.area or "").strip()
            reason = str(item.reason or item.why_worth or item.description or "").strip()
            source_candidates = cls._clean_poi_source_urls(
                [
                    *([str(item.source_url).strip()] if str(item.source_url or "").strip() else []),
                    *[str(value).strip() for value in item.source_urls if str(value).strip()],
                ]
            )
            # A single regional guide may legitimately name several nearby
            # POIs. Keep every valid citation here; concentration is a review
            # signal, not a reason to erase otherwise useful evidence.
            source_urls = source_candidates
            evidence_notes = [str(value).strip() for value in item.evidence_notes if str(value).strip()][:2]
            if not evidence_notes:
                evidence_notes = [text for text in [str(item.description or "").strip(), str(item.tips or "").strip()] if text][:2]
            confidence_value = str(item.confidence or item.xhs_appeal or "").strip().lower()
            confidence = confidence_value if confidence_value in {"high", "medium", "low"} else "high" if str(item.xhs_appeal or "").strip() in {"极高", "高", "high"} else "medium"
            if not source_urls:
                confidence = "low"
            kind = PoiGrounding._infer_kind_from_top_poi(item)
            featured.append(
                ResearchPoi(
                    name=name,
                    kind=kind,
                    category=category,
                    area=area,
                    highlights=[str(value).strip() for value in item.highlights if str(value).strip()][:4],
                    reason=reason,
                    suggested_time=str(item.suggested_time or "").strip(),
                    confidence=confidence,
                    source_urls=source_urls,
                    evidence_notes=evidence_notes,
                    caveats=[],
                    cuisine_or_type=" / ".join(item.highlights[:3]) if kind in {"food", "market", "cafe"} else "",
                    price_hint="unknown",
                    review_score="unknown",
                    review_count="unknown",
                    review_summary=str(item.xhs_appeal or "").strip(),
                    signature_dishes=item.highlights[:3] if kind in {"food", "market", "cafe"} else [],
                    reservation_hint="",
                    queue_hint="",
                )
            )
        sequencing_hints = ["Group nearby POIs into half-day blocks."] if featured else []
        crowd_notes = ["Popular photo spots are better in the morning or around sunset."] if featured else []
        poi_risks = ["Some lightweight POI fields were backfilled from top_pois recommendations and may need later evidence enrichment."] if featured else []
        source_hosts = {
            urlparse(url).netloc.casefold().removeprefix("www.")
            for poi in featured
            for url in poi.source_urls
            if urlparse(url).netloc
        }
        if len(featured) >= 4 and len(source_hosts) <= 1:
            poi_risks.append("POI 可核验来源平台过于单一；已移除首页型链接，建议重新执行原生联网检索补充详情页。")
        return {
            "featured_pois": featured,
            "candidate_areas": candidate_areas,
            "sequencing_hints": sequencing_hints,
            "crowd_notes": crowd_notes,
            "poi_risks": poi_risks,
        }

    @staticmethod
    def _infer_kind_from_top_poi(item: TopPoiItem) -> str:
        raw_kind = str(item.kind or "").strip().lower().replace("-", "_").replace(" ", "_")
        if raw_kind in {"food", "restaurant", "dining", "snack"}:
            return "food"
        if raw_kind in {"market", "night_market"}:
            return "market"
        if raw_kind in {"cafe", "coffee"}:
            return "cafe"
        if raw_kind in {"district", "street", "old_town", "ancient_town", "mixed_area"}:
            return "mixed_area"
        if raw_kind in {"experience", "workshop"}:
            return "experience"
        if raw_kind in {"attraction", "sight", "scenic", "landmark"}:
            return "attraction"
        category = f"{item.category} {' '.join(item.highlights)}".lower()
        if any(token in category for token in ("美食", "cafe", "coffee", "餐", "market", "市集")):
            if "market" in category or "市集" in category:
                return "market"
            if "cafe" in category or "coffee" in category:
                return "cafe"
            return "food"
        if any(token in category for token in ("古城", "古镇", "街区", "town", "city")):
            return "mixed_area"
        return "attraction"


class DailyForecast(BaseModel):
    date: date
    forecast_type: str = Field(default="unknown")
    condition: str = Field(default="")
    temperature_min_c: str = Field(default="")
    temperature_max_c: str = Field(default="")
    precipitation_probability: str = Field(default="")
    wind: str = Field(default="")
    outlook: str = Field(default="")
    timing_advice: str = Field(default="")
    risk: str = Field(default="")
    forecast_updated_at: str = Field(default="unknown")
    checked_at: str = Field(default="")
    source_urls: list[str] = Field(default_factory=list)
    evidence_status: str = Field(default="unknown")
    evidence_checked_at: str = Field(default="")
    evidence_reason: str = Field(default="")
    field_evidence: dict[str, str] = Field(default_factory=dict)

    @field_validator(
        "forecast_type",
        "condition",
        "temperature_min_c",
        "temperature_max_c",
        "precipitation_probability",
        "wind",
        "forecast_updated_at",
        "checked_at",
        mode="before",
    )
    @classmethod
    def _coerce_display_value(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    @field_validator("precipitation_probability", mode="before")
    @classmethod
    def _coerce_unknown_probability(cls, value: Any) -> str:
        normalized = str(value or "").strip()
        if normalized.casefold() in {"unknown", "n/a", "na", "not available", "未提供", "暂无"}:
            return ""
        return normalized

    @model_validator(mode="after")
    def _prevent_monthly_sources_from_claiming_short_range(self):
        monthly_markers = (
            "monthly", "month-weather", "january-weather", "february-weather", "march-weather",
            "april-weather", "may-weather", "june-weather", "july-weather", "august-weather",
            "september-weather", "october-weather", "november-weather", "december-weather",
        )
        uses_monthly_source = any(
            any(marker in str(url).casefold() for marker in monthly_markers)
            or bool(re.search(r"/20\d{4}(?:\.html|/|$)", str(url).casefold()))
            for url in self.source_urls
        )
        required_values = (
            self.condition,
            self.temperature_min_c,
            self.temperature_max_c,
            self.checked_at,
        )
        if self.forecast_type == "short_range" and (uses_monthly_source or not all(required_values) or not self.source_urls):
            self.forecast_type = "seasonal_reference" if uses_monthly_source else "unknown"
            warning = "该来源未形成字段完整的最新逐日预报，仅按参考信息使用。"
            self.risk = f"{self.risk.rstrip('。')}；{warning}" if self.risk.strip() else warning
        return self


class WeatherGuidance(BaseModel):
    overall_outlook: str = Field(min_length=1)
    source_urls: list[str] = Field(default_factory=list)
    daily_outlook: list[str] = Field(default_factory=list)
    daily_forecasts: list[DailyForecast] = Field(default_factory=list)
    segments: list["WeatherSegment"] = Field(default_factory=list)
    packing_notes: list[str] = Field(default_factory=list)
    timing_guidance: list[str] = Field(default_factory=list)
    weather_risks: list[str] = Field(default_factory=list)


class WeatherSegment(BaseModel):
    name: str = Field(default="")
    date_range: str = Field(default="")
    outlook: str = Field(default="")
    temperature_range: str = Field(default="")
    clothing_advice: list[str] = Field(default_factory=list)
    outdoor_notes: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


class FoodPoi(BaseModel):
    name: str = Field(min_length=1)
    area: str = Field(default="")
    cuisine_or_type: str = Field(default="")
    reason: str = Field(default="")
    suggested_time: str = Field(default="")
    price_hint: str = Field(default="unknown")
    price_checked_at: str = Field(default="unknown")
    price_valid_for: str = Field(default="")
    review_score: str = Field(default="unknown")
    review_count: str = Field(default="unknown")
    review_summary: str = Field(default="")
    signature_dishes: list[str] = Field(default_factory=list)
    reservation_hint: str = Field(default="")
    queue_hint: str = Field(default="")
    confidence: str = Field(default="low")
    caveats: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)


class FoodRecommendation(BaseModel):
    candidate_areas: list[str] = Field(default_factory=list)
    featured_pois: list[FoodPoi] = Field(default_factory=list)
    meal_strategy: list[str] = Field(default_factory=list)
    price_notes: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    food_risks: list[str] = Field(default_factory=list)


WeatherGuidance.model_rebuild()


class HotelCandidate(HotelEvidence):
    name: str = Field(min_length=1)
    city: str = Field(default="")
    area: str = Field(default="")
    address: str = Field(default="")
    hotel_type: str = Field(default="")
    reason: str = Field(default="")
    price_hint: str = Field(default="")
    price_checked_at: str = Field(default="")
    price_valid_for: str = Field(default="")
    review_score: str = Field(default="")
    review_count: str = Field(default="")
    review_summary: str = Field(default="")
    preference_match: str = Field(default="")
    booking_confidence: str = Field(default="")
    caveats: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    source_page_titles: list[str] = Field(default_factory=list)


class HotelRecommendation(BaseModel):
    recommended_areas: list[str] = Field(default_factory=list)
    final_recommended_hotel: HotelCandidate | None = None
    hotel_candidates: list[HotelCandidate] = Field(default_factory=list)
    stay_strategy: list[str] = Field(default_factory=list)
    budget_notes: list[str] = Field(default_factory=list)
    price_timeliness_notes: list[str] = Field(default_factory=list)
    review_notes: list[str] = Field(default_factory=list)
    preference_match_notes: list[str] = Field(default_factory=list)
    hotel_risks: list[str] = Field(default_factory=list)


class TransportOption(BaseModel):
    mode: str = Field(default="")
    route: str = Field(default="")
    duration_hint: str = Field(default="")
    price_hint: str = Field(default="")
    booking_window: str = Field(default="")
    reason: str = Field(default="")
    official_booking_url: str = Field(default="")
    booking_required: bool = False
    reservation_required: bool = False
    booking_notes: list[str] = Field(default_factory=list)

    @field_validator("booking_required", "reservation_required", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "y", "required"}:
            return True
        if normalized in {"0", "false", "no", "n", "not_required"}:
            return False
        return False


class TransportGuidance(BaseModel):
    legs: list[TransportLeg] = Field(default_factory=list)
    service_candidates: list[TransportServiceCandidate] = Field(default_factory=list)
    intercity_options: list[TransportOption] = Field(default_factory=list)
    arrival_strategy: list[str] = Field(default_factory=list)
    local_mobility_strategy: list[str] = Field(default_factory=list)
    pass_or_ticket_notes: list[str] = Field(default_factory=list)
    budget_notes: list[str] = Field(default_factory=list)
    transport_risks: list[str] = Field(default_factory=list)
    sequencing_constraints: list[str] = Field(default_factory=list)
    estimated_intercity_cost: float = 0.0
    estimated_local_transport_cost: float = 0.0
    departure_transfer_minutes: int = 0
    station_buffer_minutes: int = 45
    luggage_buffer_minutes: int = 30
    minimum_departure_buffer_minutes: int = 120
    summary: str = Field(default="")
    recommended_option: str = Field(default="")
    booking_required: bool = False
    official_booking_url: str = Field(default="")
    booking_window: str = Field(default="")
    reminders: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)

    @field_validator("legs", mode="before")
    @classmethod
    def _infer_missing_leg_scopes(cls, value: Any):
        if not isinstance(value, list):
            return value
        legs = [dict(item) if isinstance(item, dict) else item for item in value]
        unresolved: list[tuple[int, dict[str, Any]]] = []
        local_modes = ("metro", "subway", "bus", "taxi", "walk", "local", "市内", "地铁", "公交", "步行")
        for index, leg in enumerate(legs):
            if not isinstance(leg, dict):
                continue
            if not leg.get("scope") and leg.get("type"):
                leg["scope"] = leg["type"]
            if leg.get("scope"):
                continue
            mode = str(leg.get("mode") or "").casefold()
            origin = normalize_identity(str(leg.get("origin") or ""))
            destination = normalize_identity(str(leg.get("destination") or ""))
            if any(token in mode for token in local_modes) or (origin and origin == destination):
                leg["scope"] = "local"
            else:
                unresolved.append((index, leg))
        unresolved.sort(key=lambda row: (str(row[1].get("departure_date") or ""), row[0]))
        if len(unresolved) == 1:
            unresolved[0][1]["scope"] = "intercity"
        elif unresolved:
            unresolved[0][1]["scope"] = "outbound"
            unresolved[-1][1]["scope"] = "return"
            for _, leg in unresolved[1:-1]:
                leg["scope"] = "intercity"
        return legs

    @field_validator("estimated_intercity_cost", "estimated_local_transport_cost", mode="before")
    @classmethod
    def _coerce_cost(cls, value: Any) -> float:
        if value is None:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            match = re.search(r"-?\d+(?:\.\d+)?", str(value))
            return float(match.group()) if match else 0.0

    @field_validator(
        "departure_transfer_minutes",
        "station_buffer_minutes",
        "luggage_buffer_minutes",
        "minimum_departure_buffer_minutes",
        mode="before",
    )
    @classmethod
    def _coerce_minutes(cls, value: Any) -> int:
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            return 0

    @field_validator("booking_required", mode="before")
    @classmethod
    def _coerce_bool(cls, value: Any) -> bool:
        if isinstance(value, bool):
            return value
        normalized = str(value or "").strip().lower()
        if normalized in {"1", "true", "yes", "y", "required"}:
            return True
        if normalized in {"0", "false", "no", "n", "not_required"}:
            return False
        return False




def extract_json_payloads(content: str) -> list[dict[str, Any]]:
    candidate = str(content).strip()
    if not candidate:
        raise ValueError("Role response was empty")

    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        candidate = "\n".join(lines).strip()

    decoder = json.JSONDecoder()
    payloads: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(candidate):
        start = candidate.find("{", cursor)
        if start == -1:
            break
        try:
            payload, end = decoder.raw_decode(candidate[start:])
        except json.JSONDecodeError:
            cursor = start + 1
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
        cursor = start + end

    if not payloads:
        raise ValueError("Role response did not contain a valid JSON object")
    return payloads


def parse_structured_response(content: str, model_cls: type[ModelT]) -> ModelT:
    valid_payloads: list[ModelT] = []
    validation_errors: list[str] = []
    for payload in extract_json_payloads(content):
        try:
            valid_payloads.append(model_cls.model_validate(payload))
        except ValidationError as exc:
            validation_errors.append(str(exc))

    if not valid_payloads:
        detail = validation_errors[-1] if validation_errors else "no valid JSON object"
        raise ValueError(detail)

    if len(valid_payloads) > 1:
        signatures = {
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            for item in valid_payloads
        }
        qualifier = "conflicting" if len(signatures) > 1 else "duplicate"
        _LOGGER.warning(
            "Role response contained %d %s valid JSON objects for %s; using the last object.",
            len(valid_payloads),
            qualifier,
            model_cls.__name__,
        )
    return valid_payloads[-1]
