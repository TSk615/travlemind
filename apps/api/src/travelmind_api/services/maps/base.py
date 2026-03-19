from __future__ import annotations

from math import isfinite
from typing import Literal, Protocol

from pydantic import BaseModel, Field, field_validator

TravelMode = Literal["walking", "driving", "transit", "cycling", "mixed"]


class GeoPoint(BaseModel):
    lat: float
    lng: float

    @field_validator("lat", "lng")
    @classmethod
    def validate_coordinate(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("Coordinates must be finite numbers")
        return value


class PostalAddress(BaseModel):
    formatted: str
    city: str | None = None
    district: str | None = None
    country: str | None = None


class PoiLocation(BaseModel):
    coordinates: GeoPoint
    address: PostalAddress
    timezone: str | None = None


class PoiSearchResult(BaseModel):
    id: str
    provider: str
    name: str
    city: str | None = None
    category: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    location: PoiLocation
    relevance_score: float = 0.0


class PoiDetail(PoiSearchResult):
    opening_hours: list[str] = Field(default_factory=list)
    official_url: str | None = None
    price_level: str | None = None
    phone: str | None = None
    raw_payload: dict[str, str] = Field(default_factory=dict)


class RouteStop(BaseModel):
    stop_id: str
    name: str
    city: str | None = None
    poi_id: str | None = None
    coordinates: GeoPoint


class RouteEstimate(BaseModel):
    provider: str
    mode: TravelMode
    origin: RouteStop
    destination: RouteStop
    distance_meters: int
    duration_minutes: int
    summary: str
    polyline: list[GeoPoint] = Field(default_factory=list)


class RouteMatrixCell(BaseModel):
    origin_stop_id: str
    destination_stop_id: str
    distance_meters: int
    duration_minutes: int


class RouteMatrix(BaseModel):
    provider: str
    mode: TravelMode
    stops: list[RouteStop]
    cells: list[RouteMatrixCell]


class MapsPoiProvider(Protocol):
    provider_name: str

    def search_pois(self, query: str, city: str | None = None, limit: int = 5) -> list[PoiSearchResult]:
        ...

    def get_poi_detail(self, id: str) -> PoiDetail | None:
        ...

    def estimate_route(self, origin: RouteStop, destination: RouteStop, mode: TravelMode) -> RouteEstimate:
        ...

    def batch_route_matrix(self, stops: list[RouteStop], mode: TravelMode = "walking") -> RouteMatrix:
        ...


def poi_to_route_stop(poi: PoiSearchResult | PoiDetail) -> RouteStop:
    return RouteStop(
        stop_id=poi.id,
        name=poi.name,
        city=poi.city,
        poi_id=poi.id,
        coordinates=poi.location.coordinates,
    )