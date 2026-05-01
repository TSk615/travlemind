from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import unquote, urlparse

from travelmind_api.api.schemas.search import ScoreBreakdown, SearchDocumentResponse, SearchGeoPoint
from travelmind_api.core.security import generate_identifier
from travelmind_api.services.search_connector import ConfiguredSearchGateway, SearchServiceConfig
from travelmind_api.services.xhs_account import load_xhs_search_state, mark_xhs_session_available, mark_xhs_session_expired
from travelmind_api.services.xhs_crawler import XhsCrawlerClient, XhsCrawlerConfig, XhsCrawlerPost, XhsCrawlerSessionExpiredError

_LOGGER = logging.getLogger(__name__)

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

_PLATFORM_PRIORITY = {
    "official-tourism": 0,
    "exa": 1,
    "groksearch": 1,
    "tavily": 1,
    "xiaohongshu": 2,
    "manual-link": 3,
}

_SOCIAL_MAX_DOCS = 10
_GENERIC_FOCUS_TERMS = {
    "travel",
    "trip",
    "guide",
    "best",
    "city",
    "hotel",
    "stay",
    "where",
    "to",
    "for",
    "itinerary",
    "route",
    "tour",
    "旅游",
    "攻略",
    "旅行",
    "行程",
    "路线",
    "住哪里",
    "酒店",
    "推荐",
    "避坑",
    "打卡",
}
_XHS_AD_MARKERS = {
    "ad",
    "sponsored",
    "promotion",
    "partner",
    "advertorial",
    "推广",
    "广告",
    "合作",
    "团购",
    "折扣",
    "探店",
    "种草",
}



def search_documents(
    query: str,
    destination: str | None,
    manual_links: list[str],
    *,
    interests: list[str] | None = None,
    social_context: str = "general",
    search_service_config: SearchServiceConfig | None = None,
    xhs_source_enabled: bool = True,
    xhs_user_id: str | None = None,
) -> list[SearchDocumentResponse]:
    query_text = _clean_text(query) or ""
    clean_destination = _clean_text(destination)
    normalized_destination = clean_destination.casefold() if clean_destination else None
    results: list[SearchDocumentResponse] = []

    for document in SEED_DOCUMENTS:
        document_destination = str(document["destination"]).casefold()
        if normalized_destination and document_destination != normalized_destination:
            continue
        if normalized_destination or _query_matches_document(document, query_text.casefold()):
            results.append(_build_seed_document(query_text, clean_destination, document))

    if search_service_config is not None:
        results.extend(_search_remote_documents(query_text, clean_destination, search_service_config))

    if xhs_source_enabled:
        results.extend(_search_xhs_documents(query_text, clean_destination, interests or [], social_context=social_context, xhs_user_id=xhs_user_id))

    for link in _normalize_manual_links(manual_links):
        results.append(_build_manual_document(query_text, clean_destination, link))

    return _sort_and_dedupe_documents(results)



def _build_seed_document(query: str, destination: str | None, document: dict[str, Any]) -> SearchDocumentResponse:
    return SearchDocumentResponse(
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
        image_urls=list(document.get("image_urls") or []),
        source_type=document["source_type"],
        scores=_score_document(query, document["platform"], destination, title=document.get("title"), summary=document.get("summary")),
    )



def _search_remote_documents(query: str, destination: str | None, config: SearchServiceConfig) -> list[SearchDocumentResponse]:
    normalized_query = _clean_text(query)
    if not normalized_query:
        return []
    remote_query = normalized_query
    if destination and destination.casefold() not in normalized_query.casefold():
        remote_query = f"{destination} {normalized_query}".strip()

    try:
        gateway = ConfiguredSearchGateway(config)
        available_tools = gateway.available_tools()
        if config.provider == "groksearch" and "web_search" in available_tools:
            payload = gateway.call_operation("web_search", {"query": remote_query})
        elif "web_search_exa" in available_tools:
            payload = gateway.call_operation("web_search_exa", {"query": remote_query, "numResults": 8})
        elif "search" in available_tools:
            payload = gateway.call_operation("search", {"query": remote_query, "num_results": 8, "include_text": True})
        elif "deep_search_exa" in available_tools:
            payload = gateway.call_operation("deep_search_exa", {"objective": remote_query, "type": "deep", "numResults": 8})
        elif "answer" in available_tools:
            payload = gateway.call_operation("answer", {"query": remote_query, "include_text": True})
        else:
            return []
    except Exception as exc:
        _LOGGER.warning("Configured search service lookup failed: %s", exc)
        return []

    results: list[SearchDocumentResponse] = []
    remote_platform = "groksearch" if config.provider == "groksearch" else "tavily" if config.provider == "tavily" else "exa"
    for item in _extract_remote_search_items(payload):
        url = _extract_remote_search_url(item)
        if not url:
            continue
        title = _clean_text(str(item.get("title") or item.get("name") or url))
        summary = _clean_excerpt(
            str(
                item.get("text")
                or item.get("summary")
                or item.get("snippet")
                or item.get("highlight")
                or item.get("description")
                or item.get("content")
                or item.get("answer")
                or ""
            )
        ) or f"Remote search result from configured {config.provider} {config.transport} service."
        published_at = _normalize_published_at(str(item.get("publishedDate") or item.get("published_at") or item.get("published") or ""))
        results.append(
            SearchDocumentResponse(
                id=generate_identifier("src"),
                platform=remote_platform,
                title=title or url,
                url=url,
                summary=summary,
                destination=destination,
                place_name=title,
                category="remote-search",
                author=_clean_text(str(item.get("author") or item.get("byline") or item.get("site_name") or "")),
                published_at=published_at,
                engagement_hint=None,
                source_tags=[],
                image_urls=[],
                source_type=f"search-service-{config.transport}",
                scores=_score_document(
                    normalized_query,
                    remote_platform,
                    destination,
                    title=title,
                    summary=summary,
                    published_at=published_at,
                ),
            )
        )
    return results


def _extract_remote_search_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    results = payload.get("results")
    if isinstance(results, list):
        return [item for item in results if isinstance(item, dict)]

    sources = payload.get("sources")
    if isinstance(sources, list):
        return [item for item in sources if isinstance(item, dict)]

    data = payload.get("data")
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]

    nested_result = payload.get("result")
    if isinstance(nested_result, dict):
        return _extract_remote_search_items(nested_result)

    return []


def _extract_remote_search_url(item: dict[str, Any]) -> str | None:
    for key in ("url", "link", "source", "id", "website", "href"):
        candidate = _clean_text(str(item.get(key) or ""))
        if candidate and candidate.startswith("http"):
            return candidate
    return None


def _search_xhs_documents(query: str, destination: str | None, interests: list[str], *, social_context: str, xhs_user_id: str | None) -> list[SearchDocumentResponse]:
    if not destination:
        return []
    if not xhs_user_id:
        return []

    config = XhsCrawlerConfig.from_env()
    if config is None:
        return []

    queries = _build_xhs_queries(destination, query, interests, social_context=social_context)
    if not queries:
        return []

    search_state = load_xhs_search_state(xhs_user_id)
    if not search_state.session_payload:
        return []

    try:
        posts = XhsCrawlerClient(config).search_posts(
            user_id=xhs_user_id,
            session_payload=search_state.session_payload,
            destination=destination,
            queries=queries,
            limit_per_query=config.limit_per_query,
        )
    except XhsCrawlerSessionExpiredError as exc:
        mark_xhs_session_expired(xhs_user_id, str(exc))
        _LOGGER.warning("XHS crawler session expired for user %s: %s", xhs_user_id, exc)
        return []
    except Exception as exc:
        _LOGGER.warning("XHS crawler lookup failed: %s", exc)
        return []
    else:
        mark_xhs_session_available(xhs_user_id)

    results: list[SearchDocumentResponse] = []
    for post in posts[: config.max_results]:
        summary = _clean_excerpt(post.excerpt) or _clean_text(post.title) or "Xiaohongshu destination guide post."
        results.append(
            SearchDocumentResponse(
                id=generate_identifier("src"),
                platform="xiaohongshu",
                title=_clean_text(post.title) or _trim_text(summary, 72),
                url=post.url,
                summary=summary,
                destination=destination,
                place_name=_extract_place_name(post, destination),
                category="social-guide",
                author=_clean_text(post.author),
                published_at=_normalize_published_at(post.published_at),
                engagement_hint=_clean_text(post.engagement_hint),
                source_tags=_normalize_tags(post.tags),
                image_urls=[str(item).strip() for item in post.image_urls if str(item).strip()][:6],
                source_type="social-guide-post",
                scores=_score_document(
                    query,
                    "xiaohongshu",
                    destination,
                    title=post.title,
                    summary=summary,
                    published_at=post.published_at,
                    source_tags=post.tags,
                    engagement_hint=post.engagement_hint,
                ),
            )
        )
        if len(results) >= _SOCIAL_MAX_DOCS:
            break
    return results



def _build_xhs_queries(destination: str, query: str, interests: list[str], *, social_context: str) -> list[str]:
    normalized_destination = _clean_text(destination)
    if not normalized_destination:
        return []

    focus_candidates = [_clean_text(item) for item in interests if _clean_text(item)]
    if not focus_candidates:
        extracted = _extract_query_focus(query, normalized_destination)
        if extracted:
            focus_candidates.append(extracted)

    queries = [f"{normalized_destination} \u65c5\u6e38\u653b\u7565"]
    if focus_candidates:
        queries.append(f"{normalized_destination} {focus_candidates[0]} \u653b\u7565")

    if social_context == "hotel":
        queries.append(f"{normalized_destination} \u9152\u5e97 \u63a8\u8350")
        queries.append(f"{normalized_destination} \u4f4f\u54ea\u91cc")
    elif social_context == "attraction":
        queries.append(f"{normalized_destination} \u884c\u7a0b \u8def\u7ebf")
        queries.append(f"{normalized_destination} \u907f\u5751")
    elif focus_candidates:
        queries.append(f"{normalized_destination} \u4f4f\u54ea\u91cc")
        queries.append(f"{normalized_destination} \u907f\u5751")

    deduped: list[str] = []
    seen: set[str] = set()
    for item in queries:
        normalized = item.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped[:4]



def _extract_query_focus(query: str, destination: str) -> str | None:
    cleaned = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", " ", str(query or "")).strip()
    if not cleaned:
        return None
    destination_terms = set(re.split(r"\s+", destination.casefold()))
    tokens = []
    for token in re.split(r"\s+", cleaned):
        normalized = token.casefold()
        if not normalized or normalized in _GENERIC_FOCUS_TERMS or normalized in destination_terms:
            continue
        tokens.append(token)
    if not tokens:
        return None
    return " ".join(tokens[:3])



def _score_document(
    query: str,
    platform: str,
    destination: str | None,
    *,
    title: str | None = None,
    summary: str | None = None,
    published_at: str | None = None,
    source_tags: list[str] | None = None,
    engagement_hint: str | None = None,
) -> ScoreBreakdown:
    normalized_platform = platform.strip().lower()
    if normalized_platform == "official-tourism":
        trust = 0.92
    elif normalized_platform in {"exa", "groksearch"}:
        trust = 0.84
    elif normalized_platform == "xiaohongshu":
        trust = 0.78
    else:
        trust = 0.6
    quality = _quality_score(query, title, summary, engagement_hint)
    freshness = _freshness_score(normalized_platform, published_at)
    ad_score = _ad_score(normalized_platform, title, summary, source_tags)
    final = round((trust * 0.4) + (quality * 0.25) + (freshness * 0.2) + ((1 - ad_score) * 0.15), 3)
    reasons: list[str] = []
    if normalized_platform == "official-tourism":
        reasons.append("Official tourism source")
    elif normalized_platform == "exa":
        reasons.append("Configured Exa search service")
    elif normalized_platform == "xiaohongshu":
        reasons.append("Local traveler-generated guide")
    else:
        reasons.append("User-supplied source")
    if destination:
        reasons.append(f"Scoped to {destination}")
    if published_at and normalized_platform in {"xiaohongshu", "exa"}:
        reasons.append("Freshness score uses post publish time")
    if ad_score >= 0.3:
        reasons.append("Possible promotional tone lowered the score")
    return ScoreBreakdown(
        trust_score=round(trust, 3),
        quality_score=round(quality, 3),
        freshness_score=round(freshness, 3),
        ad_score=round(ad_score, 3),
        final_score=final,
        reasons=reasons,
    )



def _quality_score(query: str, title: str | None, summary: str | None, engagement_hint: str | None) -> float:
    query_terms = {token for token in re.split(r"\s+", str(query or "").casefold()) if token}
    haystack = " ".join(part for part in [str(title or ""), str(summary or ""), str(engagement_hint or "")] if part).casefold()
    overlap = sum(1 for token in query_terms if token in haystack)
    overlap_score = min(0.2, overlap * 0.05)
    length_score = min(0.18, len(str(summary or "")) / 800)
    return round(min(0.95, 0.58 + overlap_score + length_score), 3)



def _freshness_score(platform: str, published_at: str | None) -> float:
    if platform == "official-tourism":
        return 0.7
    if platform not in {"xiaohongshu", "exa"}:
        return 0.55
    normalized = _normalize_published_at(published_at)
    if not normalized:
        return 0.5
    try:
        published = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError:
        return 0.5
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    age_days = max((datetime.now(timezone.utc) - published.astimezone(timezone.utc)).days, 0)
    if age_days <= 30:
        return 0.92
    if age_days <= 90:
        return 0.82
    if age_days <= 365:
        return 0.68
    return 0.54



def _ad_score(platform: str, title: str | None, summary: str | None, source_tags: list[str] | None) -> float:
    if platform == "official-tourism":
        return 0.08
    combined = " ".join([str(title or ""), str(summary or ""), " ".join(source_tags or [])]).casefold()
    marker_hits = sum(1 for marker in _XHS_AD_MARKERS if marker in combined)
    if platform == "xiaohongshu":
        return min(0.5, 0.14 + (marker_hits * 0.08))
    if platform == "exa":
        return min(0.24, 0.1 + (marker_hits * 0.04))
    return 0.2



def _clean_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(str(value).split()).strip()
    return cleaned or None



def _clean_excerpt(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    return _trim_text(cleaned, 320)



def _trim_text(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 1, 1)].rstrip()}..."



def _normalize_tags(tags: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in tags or []:
        candidate = _clean_text(item)
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized[:8]



def _normalize_published_at(value: str | None) -> str | None:
    candidate = _clean_text(value)
    if not candidate:
        return None
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")



def _extract_place_name(post: XhsCrawlerPost, destination: str) -> str | None:
    title = _clean_text(post.title)
    if title and destination.casefold() not in title.casefold():
        return title
    destination_hint = _clean_text(post.raw_destination_hint)
    if destination_hint and destination_hint.casefold() != destination.casefold():
        return destination_hint
    return None



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
    host = parsed.netloc.split("@")[ -1].split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return _humanize_slug(host.split(".")[0]) or host



def _build_manual_document(query: str, destination: str | None, link: str) -> SearchDocumentResponse:
    parsed = urlparse(link)
    host = parsed.netloc.split("@")[ -1].split(":")[0] or "manual-source"
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
        image_urls=[],
        source_type="manual-link",
        scores=_score_document(query, "manual-link", destination, title=place_name, summary=host),
    )



def _sort_and_dedupe_documents(documents: list[SearchDocumentResponse]) -> list[SearchDocumentResponse]:
    ordered = sorted(
        documents,
        key=lambda doc: (
            _PLATFORM_PRIORITY.get(doc.platform, 9),
            -(doc.scores.final_score or 0.0),
            doc.title.casefold(),
        ),
    )
    results: list[SearchDocumentResponse] = []
    seen_urls: set[str] = set()
    for document in ordered:
        dedupe_key = _manual_link_dedupe_key(document.url)
        if dedupe_key in seen_urls:
            continue
        seen_urls.add(dedupe_key)
        results.append(document)
    return results
