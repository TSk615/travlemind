"""Shared evidence fields carried unchanged from planning through API serialization."""
from datetime import date
import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

EvidenceStatus = Literal["verified", "referenced", "conflicted", "unknown"]


class BookingDetails(BaseModel):
    price_status: Literal["unknown", "estimated", "verified", "free"] = "unknown"
    transport_scope: Literal["outbound", "return", "intercity", "local"] | None = None
    passenger_count: int | None = Field(default=None, ge=1)
    unit_price: float | None = Field(default=None, ge=0)
    duration_minutes_min: int | None = Field(default=None, gt=0)
    check_in_date: date | None = None
    check_out_date: date | None = None
    room_count: int | None = Field(default=None, ge=1)
    nights: int | None = Field(default=None, ge=1)
    early_check_in_confirmed: bool = False
    schedule_status: Literal["unknown", "reference", "date_specific"] = "unknown"
    evidence_status: EvidenceStatus = "unknown"
    evidence_checked_at: str | None = None
    evidence_reason: str | None = None

    @field_validator("transport_scope", mode="before")
    @classmethod
    def normalize_transport_scope(cls, value):
        normalized = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
        aliases = {
            "arrival": "local",
            "arrival_transfer": "local",
            "station_transfer": "local",
            "airport_transfer": "local",
            "urban": "local",
            "city": "local",
            "in_city": "local",
        }
        return aliases.get(normalized, value)


class TransportLeg(BaseModel):
    scope: Literal["outbound", "return", "intercity", "local"]
    origin: str
    destination: str
    departure_date: date
    arrival_date: date | None = None
    mode: str = ""
    passenger_count: int = Field(default=1, ge=1)
    estimated_total: float | None = Field(default=None, ge=0)
    unit_price: float | None = Field(default=None, ge=0)
    duration_minutes_min: int | None = Field(default=None, gt=0)
    duration_minutes_max: int | None = Field(default=None, gt=0)
    price_status: Literal["unknown", "estimated", "verified"] = "unknown"
    pricing_note: str = ""
    source_urls: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_type_key(cls, value):
        if isinstance(value, dict):
            value = dict(value)
            if not value.get("scope") and value.get("type"):
                value["scope"] = value["type"]
            try:
                unit_price = float(value["unit_price"])
                estimated_total = float(value["estimated_total"])
                passenger_count = int(value.get("passenger_count") or 1)
            except (KeyError, TypeError, ValueError):
                return value
            if value.get("scope") == "local" and abs(estimated_total - unit_price * passenger_count) > .02:
                value["unit_price"] = None
                value["pricing_note"] = "该段为跨日市内交通汇总，总额保留；模型提供的单价口径不一致，已清空待核实。"
            return value
        return value

    @model_validator(mode="after")
    def validate_leg(self):
        if self.arrival_date and self.arrival_date < self.departure_date:
            raise ValueError("交通到达日期不能早于出发日期")
        if self.duration_minutes_min and self.duration_minutes_max and self.duration_minutes_max < self.duration_minutes_min:
            raise ValueError("交通耗时区间倒置")
        if self.unit_price is not None:
            computed = round(self.unit_price * self.passenger_count, 2)
            if self.estimated_total is not None and abs(self.estimated_total - computed) > .02:
                raise ValueError("交通总价与单价、人数不一致")
            self.estimated_total = computed
        return self


class TransportServiceCandidate(BaseModel):
    scope: Literal["outbound", "return", "intercity"]
    mode: str
    service_number: str
    origin: str
    destination: str
    departure_date: date
    departure_time: str
    arrival_date: date | None = None
    arrival_time: str
    duration_minutes: int | None = Field(default=None, gt=0)
    fare_class: str | None = None
    fare_amount: float | None = Field(default=None, ge=0)
    price_status: Literal["unknown", "estimated", "verified"] = "unknown"
    availability_status: str = "unknown"
    schedule_status: Literal["unknown", "reference", "date_specific"] = "reference"
    schedule_checked_at: str
    source_url: str
    evidence_status: EvidenceStatus = "unknown"
    evidence_checked_at: str | None = None
    evidence_reason: str | None = None
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def accept_common_search_aliases(cls, value):
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        aliases = {
            "train_no": "service_number",
            "flight_number": "service_number",
            "depart_time": "departure_time",
            "dep_time": "departure_time",
            "arrive_time": "arrival_time",
            "arr_time": "arrival_time",
            "query_time": "schedule_checked_at",
            "second_class_price": "fare_amount",
        }
        for source, target in aliases.items():
            if normalized.get(target) in {None, ""} and normalized.get(source) not in {None, ""}:
                normalized[target] = normalized[source]
        return normalized

    @field_validator("departure_time", "arrival_time")
    @classmethod
    def validate_clock(cls, value: str) -> str:
        candidate = str(value or "").strip()
        parts = candidate.split(":")
        if len(parts) != 2:
            raise ValueError("交通候选班次时间必须使用 HH:MM")
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except ValueError as exc:
            raise ValueError("交通候选班次时间必须使用 HH:MM") from exc
        if not 0 <= hour < 24 or not 0 <= minute < 60:
            raise ValueError("交通候选班次时间超出有效范围")
        return f"{hour:02d}:{minute:02d}"

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        candidate = str(value or "").strip()
        if not candidate.startswith(("http://", "https://")):
            raise ValueError("交通候选班次必须保留可访问来源 URL")
        return candidate

    @field_validator("fare_amount", mode="before")
    @classmethod
    def normalize_fare_amount(cls, value):
        if value in {None, ""}:
            return None
        if isinstance(value, (int, float)):
            return value
        match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
        return float(match.group(0)) if match else None


class HotelEvidence(BaseModel):
    identity_status: str = "model_reported"
    identity_checked_at: str | None = None
    verified_source_urls: list[str] = Field(default_factory=list)
    evidence_notes: list[str] = Field(default_factory=list)


class BudgetCompleteness(BaseModel):
    incomplete: bool = False
    unpriced_items: list[str] = Field(default_factory=list)
    transport_budget_ratio: float | None = None
