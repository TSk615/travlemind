from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from travelmind_api.api.schemas.search import ScoreBreakdown, SearchDocumentResponse, SearchGeoPoint
from travelmind_api.core.security import generate_identifier

SEED_DOCUMENTS: list[dict[str, Any]] = [
    {
        "platform": "official-tourism",
        "title": "Kyoto City Official Travel Guide",
        "url": "https://kyoto.travel/en",
        "summary": "Official seasonal guides, area introductions, and transport pointers for Kyoto.",
        "destination": "Kyoto",
        "place_name": "Kyoto",
        "category": "destination-guide",
        "opening_hours": "Online resource; venue hours vary by listing",
        "price_hint": "Mixed prices; see linked venue pages",
        "address": "Kyoto, Japan",
        "geo": SearchGeoPoint(lat=35.0116, lng=135.7681),
        "source_type": "official-guide-seed",
    },
    {
        "platform": "official-tourism",
        "title": "Japan National Tourism Organization: Kyoto",
        "url": "https://www.japan.travel/en/destinations/kansai/kyoto/",
        "summary": "National tourism entry page covering Kyoto highlights, transport basics, and neighborhoods.",
        "destination": "Kyoto",
        "place_name": "Kyoto",
        "category": "destination-guide",
        "opening_hours": "Online resource; venue hours vary by listing",
        "price_hint": "See linked attraction pages for local pricing",
        "address": "Kyoto, Japan",
        "geo": SearchGeoPoint(lat=35.0116, lng=135.7681),
        "source_type": "official-guide-seed",
    },
    {
        "platform": "official-tourism",
        "title": "Fushimi Inari Taisha Official Guide",
        "url": "https://inari.jp/en/",
        "summary": "Official shrine information for torii trails, worship etiquette, and access notes.",
        "destination": "Kyoto",
        "place_name": "Fushimi Inari Taisha",
        "category": "shrine",
        "opening_hours": "Open 24 hours",
        "price_hint": "Free admission",
        "address": "68 Fukakusa Yabunouchicho, Fushimi Ward, Kyoto 612-0882, Japan",
        "geo": SearchGeoPoint(lat=34.9671, lng=135.7727),
        "source_type": "official-attraction-seed",
    },
    {
        "platform": "official-tourism",
        "title": "Tokyo Convention and Visitors Bureau",
        "url": "https://www.gotokyo.org/en/",
        "summary": "Official Tokyo destination content with district guides, transport notes, and seasonal events.",
        "destination": "Tokyo",
        "place_name": "Tokyo",
        "category": "destination-guide",
        "opening_hours": "Online resource; venue hours vary by listing",
        "price_hint": "Mixed prices; see linked venue pages",
        "address": "Tokyo, Japan",
        "geo": SearchGeoPoint(lat=35.6762, lng=139.6503),
        "source_type": "official-guide-seed",
    },
    {
        "platform": "official-tourism",
        "title": "Senso-ji Temple Visitor Information",
        "url": "https://www.senso-ji.jp/english/",
        "summary": "Official visitor information for Senso-ji covering access, precinct highlights, and etiquette.",
        "destination": "Tokyo",
        "place_name": "Senso-ji",
        "category": "temple",
        "opening_hours": "Temple grounds open daily; check the official site for hall hours",
        "price_hint": "Free precinct access; some experiences may be extra",
        "address": "2-3-1 Asakusa, Taito City, Tokyo 111-0032, Japan",
        "geo": SearchGeoPoint(lat=35.7148, lng=139.7967),
        "source_type": "official-attraction-seed",
    },
]


def _score_document(query: str, platform: str, destination: str | None) -> ScoreBreakdown:
    trust = 0.92 if platform == "official-tourism" else 0.68
    quality = 0.75 if len(query) > 8 else 0.66
    freshness = 0.64
    ad_score = 0.08 if platform == "official-tourism" else 0.2
    final = round((trust * 0.35) + (quality * 0.25) + (freshness * 0.2) + ((1 - ad_score) * 0.2), 3)
    reasons = ["Official or user-supplied source", "Normalized for MVP ranking"]
    if destination:
        reasons.append(f"Scoped to {destination}")
    return ScoreBreakdown(
        trust_score=round(trust, 3),
        quality_score=round(quality, 3),
        freshness_score=round(freshness, 3),
        ad_score=round(ad_score, 3),
        final_score=final,
        reasons=reasons,
    )


def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split()).strip()
    return cleaned or None


def _manual_link_dedupe_key(candidate: str) -> str:
    parsed = urlparse(candidate)
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}?{parsed.query.casefold()}"


def _normalize_manual_links(manual_links: list[str]) -> list[str]:
    normalized_links: list[str] = []
    seen: set[str] = set()
    for link in manual_links:
        candidate = (link or "").strip()
        if not candidate:
            continue
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        dedupe_key = _manual_link_dedupe_key(candidate)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_links.append(candidate)
    return normalized_links


def _query_matches_document(document: dict[str, Any], query_lower: str) -> bool:
    searchable_fields = [
        document.get("title"),
        document.get("summary"),
        document.get("place_name"),
        document.get("category"),
        document.get("opening_hours"),
        document.get("price_hint"),
        document.get("address"),
    ]
    normalized = " ".join(str(value).lower() for value in searchable_fields if value)
    return query_lower in normalized


def _humanize_slug(value: str) -> str:
    cleaned = re.sub(r"\.[A-Za-z0-9]{1,6}$", "", value)
    words = [segment for segment in re.split(r"[-_+\s]+", cleaned) if segment]
    return " ".join(word.capitalize() for word in words)


def _guess_manual_place_name(link: str) -> str:
    parsed = urlparse(link)
    segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    if segments:
        title = _humanize_slug(segments[-1])
        if title:
            return title
    host = parsed.netloc.split("@")[-1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return _humanize_slug(host.split(".")[0]) or host


def _build_manual_document(query: str, destination: str | None, link: str) -> SearchDocumentResponse:
    parsed = urlparse(link)
    host = parsed.netloc.split("@")[-1].split(":")[0] or "manual-source"
    place_name = _guess_manual_place_name(link)
    return SearchDocumentResponse(
        id=generate_identifier("src"),
        platform="manual-link",
        title=f"Manual source: {place_name}",
        url=link,
        summary=f"User-provided source from {host} for {destination or 'the trip plan'}.",
        destination=destination,
        place_name=place_name,
        category="external-reference",
        opening_hours="Check source page",
        price_hint="See source page",
        address=host,
        geo=None,
        source_type="manual-link",
        scores=_score_document(query, "manual-link", destination),
    )


def search_documents(query: str, destination: str | None, manual_links: list[str]) -> list[SearchDocumentResponse]:
    query_lower = query.lower()
    clean_destination = _clean_text(destination)
    normalized_destination = clean_destination.lower() if clean_destination else None
    results: list[SearchDocumentResponse] = []

    for document in SEED_DOCUMENTS:
        document_destination = document["destination"].lower()
        if normalized_destination and document_destination != normalized_destination:
            continue
        if normalized_destination or _query_matches_document(document, query_lower):
            results.append(
                SearchDocumentResponse(
                    id=generate_identifier("src"),
                    platform=document["platform"],
                    title=document["title"],
                    url=document["url"],
                    summary=document["summary"],
                    destination=document["destination"],
                    place_name=document.get("place_name"),
                    category=document.get("category"),
                    opening_hours=document.get("opening_hours"),
                    price_hint=document.get("price_hint"),
                    address=document.get("address"),
                    geo=document.get("geo"),
                    source_type=document["source_type"],
                    scores=_score_document(query, document["platform"], clean_destination),
                )
            )

    for link in _normalize_manual_links(manual_links):
        results.append(_build_manual_document(query, clean_destination, link))

    return results
