from __future__ import annotations

from math import ceil, cos, radians, sqrt
from typing import Any

import httpx

from travelmind_api.services.maps.base import (
    GeoPoint,
    MapsPoiProvider,
    PoiDetail,
    PoiLocation,
    PoiSearchResult,
    PostalAddress,
    RouteEstimate,
    RouteMatrix,
    RouteMatrixCell,
    RouteStop,
    TravelMode,
)


class AmapMapsPoiProvider(MapsPoiProvider):
    provider_name = "amap"

    _MODE_SPEED_KMH = {
        "walking": 4.5,
        "cycling": 14.0,
        "transit": 24.0,
        "driving": 30.0,
        "mixed": 10.0,
    }

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://restapi.amap.com",
        timeout_seconds: float = 8.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        cleaned_key = api_key.strip()
        if not cleaned_key:
            raise ValueError("Amap API key is required.")
        self._api_key = cleaned_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client
        self._detail_index: dict[str, PoiDetail] = {}

    def search_pois(self, query: str, city: str | None = None, limit: int = 5) -> list[PoiSearchResult]:
        cleaned_query = (query or "").strip()
        if not cleaned_query:
            return []
        payload = self._get(
            "/v3/place/text",
            {
                "keywords": cleaned_query,
                "city": (city or "").strip(),
                "citylimit": "false",
                "offset": str(max(1, min(limit, 25))),
                "page": "1",
                "extensions": "all",
            },
        )
        pois = payload.get("pois")
        if not isinstance(pois, list):
            return []
        results: list[PoiSearchResult] = []
        for index, raw_poi in enumerate(pois[:limit], start=1):
            if not isinstance(raw_poi, dict):
                continue
            detail = self._detail_from_payload(raw_poi, relevance_score=max(1.0, float(limit + 1 - index)))
            if detail is None:
                continue
            self._detail_index[detail.id] = detail
            results.append(self._to_search_result(detail))
        return results

    def get_poi_detail(self, id: str) -> PoiDetail | None:
        if id in self._detail_index:
            return self._detail_index[id]
        cleaned_id = (id or "").strip()
        if not cleaned_id:
            return None
        payload = self._get("/v3/place/detail", {"id": cleaned_id, "extensions": "all"})
        pois = payload.get("pois")
        if not isinstance(pois, list) or not pois:
            return None
        first = pois[0]
        if not isinstance(first, dict):
            return None
        detail = self._detail_from_payload(first, relevance_score=1.0)
        if detail is not None:
            self._detail_index[detail.id] = detail
        return detail

    def estimate_route(self, origin: RouteStop, destination: RouteStop, mode: TravelMode) -> RouteEstimate:
        distance_meters = self._distance_meters(origin.coordinates, destination.coordinates)
        duration_minutes = self._duration_minutes(distance_meters, mode)
        midpoint = GeoPoint(
            lat=round((origin.coordinates.lat + destination.coordinates.lat) / 2, 6),
            lng=round((origin.coordinates.lng + destination.coordinates.lng) / 2, 6),
        )
        return RouteEstimate(
            provider=self.provider_name,
            mode=mode,
            origin=origin,
            destination=destination,
            distance_meters=distance_meters,
            duration_minutes=duration_minutes,
            summary=f"{duration_minutes} min by {mode} for about {distance_meters} m, estimated from Amap POI coordinates",
            polyline=[origin.coordinates, midpoint, destination.coordinates],
        )

    def batch_route_matrix(self, stops: list[RouteStop], mode: TravelMode = "walking") -> RouteMatrix:
        cells: list[RouteMatrixCell] = []
        for origin in stops:
            for destination in stops:
                if origin.stop_id == destination.stop_id:
                    cells.append(
                        RouteMatrixCell(
                            origin_stop_id=origin.stop_id,
                            destination_stop_id=destination.stop_id,
                            distance_meters=0,
                            duration_minutes=0,
                        )
                    )
                    continue
                estimate = self.estimate_route(origin, destination, mode)
                cells.append(
                    RouteMatrixCell(
                        origin_stop_id=origin.stop_id,
                        destination_stop_id=destination.stop_id,
                        distance_meters=estimate.distance_meters,
                        duration_minutes=estimate.duration_minutes,
                    )
                )
        return RouteMatrix(provider=self.provider_name, mode=mode, stops=stops, cells=cells)

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        request_params = {"key": self._api_key, "output": "JSON", **params}
        url = f"{self._base_url}{path}"
        if self._http_client is not None:
            response = self._http_client.get(url, params=request_params)
        else:
            with httpx.Client(timeout=self._timeout_seconds, follow_redirects=True) as client:
                response = client.get(url, params=request_params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Amap returned a non-object response.")
        if str(payload.get("status", "1")) != "1":
            info = str(payload.get("info") or "unknown error")
            infocode = str(payload.get("infocode") or "")
            detail = f" ({infocode})" if infocode else ""
            raise RuntimeError(f"Amap API request failed: {info}{detail}")
        return payload

    def _detail_from_payload(self, payload: dict[str, Any], *, relevance_score: float) -> PoiDetail | None:
        identifier = self._string_value(payload.get("id"))
        name = self._string_value(payload.get("name"))
        location = self._parse_location(payload.get("location"))
        if not identifier or not name or location is None:
            return None

        city = self._string_value(payload.get("cityname")) or None
        district = self._string_value(payload.get("adname")) or None
        address_text = self._string_value(payload.get("address"))
        formatted_address = ", ".join(part for part in [address_text, district, city] if part) or name
        category = self._string_value(payload.get("type")) or self._string_value(payload.get("typecode")) or "poi"
        summary_parts = [part for part in [category, formatted_address] if part]
        raw_payload = {
            key: self._string_value(payload.get(key))
            for key in ["id", "name", "type", "typecode", "pname", "cityname", "adname", "address", "location"]
            if self._string_value(payload.get(key))
        }
        return PoiDetail(
            id=identifier,
            provider=self.provider_name,
            name=name,
            city=city,
            category=category,
            summary=" | ".join(summary_parts) if summary_parts else name,
            tags=[value for value in category.replace("；", ";").split(";") if value],
            location=PoiLocation(
                coordinates=location,
                address=PostalAddress(
                    formatted=formatted_address,
                    city=city,
                    district=district,
                    country="China",
                ),
                timezone="Asia/Shanghai",
            ),
            relevance_score=relevance_score,
            opening_hours=self._opening_hours(payload),
            official_url=self._string_value(payload.get("website")) or None,
            price_level=None,
            phone=self._string_value(payload.get("tel")) or None,
            raw_payload={"source": "amap", **raw_payload},
        )

    def _to_search_result(self, detail: PoiDetail) -> PoiSearchResult:
        return PoiSearchResult(
            id=detail.id,
            provider=detail.provider,
            name=detail.name,
            city=detail.city,
            category=detail.category,
            summary=detail.summary,
            tags=list(detail.tags),
            location=detail.location,
            relevance_score=detail.relevance_score,
        )

    def _parse_location(self, value: Any) -> GeoPoint | None:
        text = self._string_value(value)
        if "," not in text:
            return None
        lng_text, lat_text = [part.strip() for part in text.split(",", 1)]
        try:
            return GeoPoint(lat=float(lat_text), lng=float(lng_text))
        except ValueError:
            return None

    def _opening_hours(self, payload: dict[str, Any]) -> list[str]:
        values = [
            self._string_value(payload.get("opentime_today")),
            self._string_value(payload.get("opentime_week")),
            self._string_value(payload.get("opentime")),
        ]
        return [value for value in values if value]

    def _distance_meters(self, origin: GeoPoint, destination: GeoPoint) -> int:
        lat_scale = 111_320
        lng_scale = 111_320 * cos(radians((origin.lat + destination.lat) / 2))
        delta_lat = (destination.lat - origin.lat) * lat_scale
        delta_lng = (destination.lng - origin.lng) * lng_scale
        return max(50, int(round(sqrt((delta_lat ** 2) + (delta_lng ** 2)))))

    def _duration_minutes(self, distance_meters: int, mode: TravelMode) -> int:
        speed_kmh = self._MODE_SPEED_KMH.get(mode, self._MODE_SPEED_KMH["mixed"])
        travel_hours = (distance_meters / 1000.0) / speed_kmh
        buffer_minutes = 8 if mode in {"transit", "driving", "mixed"} else 4
        return max(3, int(ceil((travel_hours * 60) + buffer_minutes)))

    def _string_value(self, value: Any) -> str:
        if value is None or isinstance(value, (list, dict)):
            return ""
        return str(value).strip()
