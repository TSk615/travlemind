from __future__ import annotations

from math import ceil, cos, radians, sqrt

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


class StubMapsPoiProvider(MapsPoiProvider):
    provider_name = "stub-maps"

    _CURATED_POIS: tuple[dict[str, object], ...] = (
        {
            "id": "stub-kyoto-ginkakuji",
            "name": "Ginkaku-ji",
            "city": "Kyoto",
            "category": "temple",
            "summary": "Historic temple complex with gardens and a calm eastern Kyoto setting.",
            "tags": ["temples", "heritage", "quiet", "slow walks"],
            "lat": 35.0271,
            "lng": 135.7982,
            "address": "2 Ginkakujicho, Sakyo Ward",
            "district": "Sakyo Ward",
            "opening_hours": ["09:00-17:00"],
            "official_url": "https://www.shokoku-ji.jp/ginkakuji/",
            "price_level": "moderate",
        },
        {
            "id": "stub-kyoto-philosophers-path",
            "name": "Philosopher's Path",
            "city": "Kyoto",
            "category": "walk",
            "summary": "Canal-side walking route with shrines, cafes, and easy pacing.",
            "tags": ["walk", "coffee", "scenic", "slow walks"],
            "lat": 35.0204,
            "lng": 135.7947,
            "address": "Jodoji Ishibashicho",
            "district": "Sakyo Ward",
            "opening_hours": ["Open all day"],
            "official_url": "https://kyoto.travel/",
            "price_level": "free",
        },
        {
            "id": "stub-kyoto-nishiki-market",
            "name": "Nishiki Market",
            "city": "Kyoto",
            "category": "food",
            "summary": "Covered market with snacks, pantry stalls, and lunch options near transit.",
            "tags": ["food", "market", "lunch", "local highlights"],
            "lat": 35.0047,
            "lng": 135.7641,
            "address": "609 Nishidaimonjicho, Nakagyo Ward",
            "district": "Nakagyo Ward",
            "opening_hours": ["10:00-18:00"],
            "official_url": "https://www.kyoto-nishiki.or.jp/",
            "price_level": "moderate",
        },
        {
            "id": "stub-kyoto-kiyomizu-dera",
            "name": "Kiyomizu-dera",
            "city": "Kyoto",
            "category": "sight",
            "summary": "Signature hillside temple with city views and dense cultural context.",
            "tags": ["temples", "views", "heritage", "local highlights"],
            "lat": 34.9948,
            "lng": 135.7850,
            "address": "294 Kiyomizu, Higashiyama Ward",
            "district": "Higashiyama Ward",
            "opening_hours": ["06:00-18:00"],
            "official_url": "https://www.kiyomizudera.or.jp/",
            "price_level": "moderate",
        },
        {
            "id": "stub-tokyo-sensoji",
            "name": "Senso-ji",
            "city": "Tokyo",
            "category": "temple",
            "summary": "Well-known Asakusa temple complex with strong first-time visitor appeal.",
            "tags": ["temples", "heritage", "local highlights"],
            "lat": 35.7148,
            "lng": 139.7967,
            "address": "2-3-1 Asakusa, Taito City",
            "district": "Taito City",
            "opening_hours": ["06:00-17:00"],
            "official_url": "https://www.senso-ji.jp/",
            "price_level": "free",
        },
    )

    _MODE_SPEED_KMH = {
        "walking": 4.5,
        "cycling": 14.0,
        "transit": 24.0,
        "driving": 30.0,
        "mixed": 10.0,
    }

    def __init__(self) -> None:
        self._detail_index = {record["id"]: self._build_detail(record) for record in self._CURATED_POIS}

    def search_pois(self, query: str, city: str | None = None, limit: int = 5) -> list[PoiSearchResult]:
        normalized_query = (query or "").strip().lower()
        normalized_city = (city or "").strip().lower()
        scored: list[tuple[int, PoiSearchResult]] = []

        for detail in self._detail_index.values():
            if normalized_city and (detail.city or "").lower() != normalized_city:
                continue
            score = self._match_score(detail, normalized_query)
            if score <= 0 and normalized_query:
                continue
            scored.append((score, self._to_search_result(detail, score)))

        if not scored:
            generic_results = self._build_generic_results(query=query, city=city, limit=limit)
            return generic_results[:limit]

        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [result for _, result in scored[:limit]]

    def get_poi_detail(self, id: str) -> PoiDetail | None:
        if id in self._detail_index:
            return self._detail_index[id]
        if id.startswith("stub-generic-"):
            return self._build_generic_detail(id)
        return None

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
            summary=f"{duration_minutes} min by {mode} for {distance_meters} m",
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

    def _match_score(self, detail: PoiDetail, normalized_query: str) -> int:
        if not normalized_query:
            return 1
        score = 0
        haystacks = [detail.name.lower(), detail.category.lower(), detail.summary.lower(), " ".join(tag.lower() for tag in detail.tags)]
        for token in normalized_query.split():
            if any(token in haystack for haystack in haystacks):
                score += 3
        if normalized_query in detail.name.lower():
            score += 2
        return score

    def _to_search_result(self, detail: PoiDetail, relevance_score: int) -> PoiSearchResult:
        return PoiSearchResult(
            id=detail.id,
            provider=detail.provider,
            name=detail.name,
            city=detail.city,
            category=detail.category,
            summary=detail.summary,
            tags=list(detail.tags),
            location=detail.location,
            relevance_score=float(relevance_score),
        )

    def _build_detail(self, record: dict[str, object]) -> PoiDetail:
        return PoiDetail(
            id=str(record["id"]),
            provider=self.provider_name,
            name=str(record["name"]),
            city=str(record.get("city") or "") or None,
            category=str(record["category"]),
            summary=str(record["summary"]),
            tags=[str(tag) for tag in record.get("tags", [])],
            location=PoiLocation(
                coordinates=GeoPoint(lat=float(record["lat"]), lng=float(record["lng"])),
                address=PostalAddress(
                    formatted=f"{record['address']}, {record['city']}",
                    city=str(record.get("city") or "") or None,
                    district=str(record.get("district") or "") or None,
                    country="Japan",
                ),
                timezone="Asia/Tokyo",
            ),
            relevance_score=1.0,
            opening_hours=[str(value) for value in record.get("opening_hours", [])],
            official_url=str(record.get("official_url") or "") or None,
            price_level=str(record.get("price_level") or "") or None,
            phone=str(record.get("phone") or "") or None,
            raw_payload={
                "source": "stub-curated",
                "district": str(record.get("district") or ""),
            },
        )

    def _build_generic_results(self, query: str, city: str | None, limit: int) -> list[PoiSearchResult]:
        seed_city = (city or "Sample City").strip() or "Sample City"
        categories = [query.strip() or "local highlights", "food", "walk"]
        results: list[PoiSearchResult] = []
        for index, category in enumerate(categories[:limit], start=1):
            detail = self._build_generic_detail(f"stub-generic-{self._slug(seed_city)}-{index}", city=seed_city, category=category)
            results.append(self._to_search_result(detail, relevance_score=max(1, 6 - index)))
        return results

    def _build_generic_detail(self, identifier: str, city: str | None = None, category: str | None = None) -> PoiDetail:
        parts = identifier.split("-")
        index = int(parts[-1]) if parts and parts[-1].isdigit() else 1
        seed_city = city or " ".join(part.title() for part in parts[2:-1]) or "Sample City"
        focus = category or ["local highlights", "food", "walk"][min(index - 1, 2)]
        lat, lng = self._city_anchor(seed_city)
        lat += 0.01 * index
        lng += 0.012 * index
        name_suffix = {
            1: "Central Landmark",
            2: "Market Hall",
            3: "Riverside Walk",
        }.get(index, "Local Stop")
        return PoiDetail(
            id=identifier,
            provider=self.provider_name,
            name=f"{seed_city} {name_suffix}",
            city=seed_city,
            category=focus,
            summary=f"Stub POI for {seed_city} focused on {focus}.",
            tags=[focus, "stub", "mvp"],
            location=PoiLocation(
                coordinates=GeoPoint(lat=round(lat, 6), lng=round(lng, 6)),
                address=PostalAddress(
                    formatted=f"{seed_city} center zone {index}",
                    city=seed_city,
                    district="Central",
                    country="Stubland",
                ),
                timezone="UTC",
            ),
            relevance_score=float(max(1, 6 - index)),
            opening_hours=["09:00-18:00"],
            official_url=None,
            price_level="moderate",
            raw_payload={"source": "stub-generic", "focus": focus},
        )

    def _city_anchor(self, city: str) -> tuple[float, float]:
        seed = sum(ord(char) for char in city.lower())
        lat = 20.0 + (seed % 4000) / 100.0
        lng = 80.0 + (seed % 5000) / 100.0
        return lat, lng

    def _distance_meters(self, origin: GeoPoint, destination: GeoPoint) -> int:
        lat_scale = 111_320
        lng_scale = 111_320 * cos(radians((origin.lat + destination.lat) / 2))
        delta_lat = (destination.lat - origin.lat) * lat_scale
        delta_lng = (destination.lng - origin.lng) * lng_scale
        return max(150, int(round(sqrt((delta_lat ** 2) + (delta_lng ** 2)))))

    def _duration_minutes(self, distance_meters: int, mode: TravelMode) -> int:
        speed_kmh = self._MODE_SPEED_KMH.get(mode, self._MODE_SPEED_KMH["mixed"])
        travel_hours = (distance_meters / 1000.0) / speed_kmh
        buffer_minutes = 8 if mode in {"transit", "driving", "mixed"} else 4
        return max(4, int(ceil((travel_hours * 60) + buffer_minutes)))

    def _slug(self, value: str) -> str:
        return "-".join(part for part in value.lower().replace("'", "").split() if part)