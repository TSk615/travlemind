from __future__ import annotations

import json
import re
from copy import deepcopy
from datetime import timedelta
from typing import Any

from travelmind_api.agents.base import PlanningRequest


_TOOL_RESULT_URL_METADATA_KEYS = {
    "url",
    "urls",
    "link",
    "links",
    "href",
    "website",
    "crawl_urls",
    "citations",
    "source_url",
    "source_urls",
}


class PlanningPayloadMixin:
    """Credential-free role payload preparation and context compaction."""

    def _build_role_prompt_payload(
        self,
        enriched_payload: dict[str, Any],
        *,
        role_name: str = "",
    ) -> dict[str, Any]:
        prompt_payload = deepcopy(enriched_payload)
        tool_results = prompt_payload.get("tool_results")
        if isinstance(tool_results, dict):
            if role_name == "poi_specialist":
                prompt_payload["tool_results"] = self._compact_poi_tool_results_for_prompt(tool_results)
            elif role_name in {"hotel_specialist", "transport_specialist"}:
                prompt_payload["tool_results"] = self._compact_grounding_tool_results_for_prompt(tool_results)
            else:
                prompt_payload["tool_results"] = self._strip_tool_url_metadata(tool_results)
        return prompt_payload

    def _compact_grounding_tool_results_for_prompt(self, tool_results: dict[str, Any]) -> dict[str, Any]:
        crawl_urls = tool_results.get("crawl_urls") if isinstance(tool_results.get("crawl_urls"), list) else []
        compact: dict[str, Any] = {
            "research_tool": tool_results.get("research_tool"),
            "search_tool": tool_results.get("search_tool"),
            "search_query": tool_results.get("search_query"),
            "fallback_search_tool": tool_results.get("fallback_search_tool"),
            "crawl_tool": tool_results.get("crawl_tool"),
            "crawl_urls": [str(item).strip() for item in crawl_urls if str(item).strip()][:3],
            "citations": self._extract_urls_from_search_result(tool_results)[:12],
            "evidence_brief": self._build_poi_evidence_brief(tool_results, limit=10),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}

    def _compact_poi_tool_results_for_prompt(self, tool_results: dict[str, Any]) -> dict[str, Any]:
        crawl_urls = tool_results.get("crawl_urls") if isinstance(tool_results.get("crawl_urls"), list) else []
        citations = self._extract_urls_from_search_result(tool_results)[:10]
        compact: dict[str, Any] = {
            "poi_source": tool_results.get("poi_source"),
            "research_tool": tool_results.get("research_tool"),
            "search_tool": tool_results.get("search_tool"),
            "search_query": tool_results.get("search_query"),
            "answer": self._compact_tool_value_for_prompt(
                tool_results.get("answer"),
                max_list_items=4,
                text_limit=700,
            ),
            "crawl_tool": tool_results.get("crawl_tool"),
            "crawl_urls": [str(item).strip() for item in crawl_urls if str(item).strip()][:3],
            "citations": citations,
            "evidence_brief": self._build_poi_evidence_brief(tool_results, limit=12),
        }
        return {key: value for key, value in compact.items() if value not in (None, "", [], {})}

    def _build_poi_evidence_brief(
        self,
        tool_results: dict[str, Any],
        *,
        limit: int,
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        def clean_text(value: Any, *, text_limit: int = 320) -> str:
            normalized = re.sub(r"\s+", " ", str(value or "")).strip()
            if len(normalized) <= text_limit:
                return normalized
            return f"{normalized[:text_limit].rstrip()}..."

        def add_record(
            *,
            title: Any = "",
            url: Any = "",
            summary: Any = "",
            source_type: str = "",
            place_name: Any = "",
            category: Any = "",
        ) -> None:
            if len(records) >= limit:
                return
            title_text = clean_text(title, text_limit=90)
            url_text = str(url or "").strip()
            summary_text = clean_text(summary, text_limit=360)
            place_text = clean_text(place_name, text_limit=60)
            category_text = clean_text(category, text_limit=60)
            if not any((title_text, url_text, summary_text, place_text, category_text)):
                return
            key = ((url_text or title_text).casefold(), summary_text[:80].casefold())
            if key in seen:
                return
            seen.add(key)
            record = {
                "source_type": source_type,
                "title": title_text,
                "url": url_text,
                "place_name": place_text,
                "category": category_text,
                "summary": summary_text,
            }
            records.append({key: value for key, value in record.items() if value not in (None, "", [], {})})

        grounding_docs = (
            tool_results.get("grounding_docs")
            if isinstance(tool_results.get("grounding_docs"), list)
            else []
        )
        for doc in grounding_docs:
            if not isinstance(doc, dict):
                continue
            add_record(
                title=doc.get("title") or doc.get("name"),
                url=doc.get("url") or doc.get("source_url"),
                summary=doc.get("summary") or doc.get("snippet") or doc.get("description"),
                source_type=str(doc.get("source_type") or doc.get("platform") or "grounding_doc"),
                place_name=doc.get("place_name"),
                category=doc.get("category"),
            )

        def visit_source_items(value: Any, *, source_type: str) -> None:
            if len(records) >= limit:
                return
            if isinstance(value, dict):
                sources = value.get("sources") or value.get("results")
                if isinstance(sources, list):
                    for item in sources[:8]:
                        visit_source_items(item, source_type=source_type)
                    return
                add_record(
                    title=value.get("title") or value.get("name") or value.get("source"),
                    url=(
                        value.get("url")
                        or value.get("link")
                        or value.get("website")
                        or value.get("source_url")
                    ),
                    summary=(
                        value.get("snippet")
                        or value.get("summary")
                        or value.get("description")
                        or value.get("content")
                        or value.get("text")
                    ),
                    source_type=source_type,
                    place_name=value.get("place_name"),
                    category=value.get("category"),
                )
                return
            if isinstance(value, list):
                for item in value[:8]:
                    visit_source_items(item, source_type=source_type)

        visit_source_items(tool_results.get("answer"), source_type="answer_source")
        visit_source_items(tool_results.get("search"), source_type="search_source")

        crawl_value = tool_results.get("crawl")
        if isinstance(crawl_value, dict) and isinstance(crawl_value.get("results"), list):
            crawl_items = crawl_value.get("results") or []
        else:
            crawl_items = crawl_value if isinstance(crawl_value, list) else [crawl_value]
        for item in crawl_items[:3]:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or item.get("markdown") or item.get("raw_content")
                add_record(
                    title=item.get("title") or item.get("name") or "Fetched page excerpt",
                    url=item.get("url") or item.get("source_url"),
                    summary=text,
                    source_type="crawl_excerpt",
                )
            elif isinstance(item, str):
                add_record(title="Fetched page excerpt", summary=item, source_type="crawl_excerpt")

        if not records:
            for key in ("answer", "search", "crawl"):
                value = tool_results.get(key)
                if value is not None:
                    add_record(
                        title=key,
                        summary=(
                            json.dumps(value, ensure_ascii=False)
                            if not isinstance(value, str)
                            else value
                        ),
                        source_type=key,
                    )
        return records

    def _compact_tool_value_for_prompt(
        self,
        value: Any,
        *,
        max_list_items: int,
        text_limit: int,
    ) -> Any:
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            preferred_keys = (
                "url",
                "link",
                "website",
                "source_url",
                "title",
                "name",
                "source",
                "snippet",
                "summary",
                "description",
                "answer",
                "text",
                "content",
                "markdown",
                "raw_content",
                "published_date",
                "score",
                "results",
                "sources",
            )
            for key in preferred_keys:
                if key not in value:
                    continue
                item = value.get(key)
                compact_value = self._compact_tool_value_for_prompt(
                    item,
                    max_list_items=max_list_items,
                    text_limit=text_limit,
                )
                if compact_value not in (None, "", [], {}):
                    compact[key] = compact_value
            if compact:
                return compact
            for key, item in list(value.items())[:8]:
                compact_value = self._compact_tool_value_for_prompt(
                    item,
                    max_list_items=max_list_items,
                    text_limit=text_limit,
                )
                if compact_value not in (None, "", [], {}):
                    compact[str(key)] = compact_value
            return compact
        if isinstance(value, list):
            return [
                compact_item
                for compact_item in (
                    self._compact_tool_value_for_prompt(
                        item,
                        max_list_items=max_list_items,
                        text_limit=text_limit,
                    )
                    for item in value[:max_list_items]
                )
                if compact_item not in (None, "", [], {})
            ]
        if isinstance(value, str):
            normalized = re.sub(r"\s+", " ", value).strip()
            if len(normalized) <= text_limit:
                return normalized
            return f"{normalized[:text_limit].rstrip()} ... [truncated {len(normalized) - text_limit} chars]"
        return value

    def _strip_tool_url_metadata(self, value: Any) -> Any:
        if isinstance(value, dict):
            stripped: dict[str, Any] = {}
            for key, item in value.items():
                normalized_key = str(key).strip().lower()
                if normalized_key in _TOOL_RESULT_URL_METADATA_KEYS:
                    continue
                stripped[key] = self._strip_tool_url_metadata(item)
            return stripped
        if isinstance(value, list):
            return [self._strip_tool_url_metadata(item) for item in value]
        if isinstance(value, str):
            return re.sub(r"https?://[^\s<>'\"\]]+", "[link omitted]", value)
        return value

    def _extract_urls_from_search_result(self, search_result: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()

        def record(candidate: str) -> None:
            normalized = candidate.strip()
            if ")[[" in normalized:
                normalized = normalized.split(")[[", 1)[0]
            normalized = normalized.rstrip(").,;]")
            if not normalized.startswith("http") or normalized in seen:
                return
            seen.add(normalized)
            urls.append(normalized)

        def visit(value: Any, parent_key: str = "") -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    normalized_key = str(key).strip().lower()
                    if normalized_key in {"url", "id", "link", "source", "website"} and isinstance(item, str):
                        record(item)
                    visit(item, normalized_key)
                return
            if isinstance(value, list):
                for item in value:
                    visit(item, parent_key)
                return
            if isinstance(value, str):
                if parent_key in {"url", "id", "link", "source", "website"}:
                    record(value)
                for match in re.findall(r"https?://[^\s<>'\"\]]+", value):
                    record(match)

        visit(search_result)
        return urls


_PAYLOAD_BUILDER = PlanningPayloadMixin()


def build_role_prompt_payload(
    enriched_payload: dict[str, Any],
    *,
    role_name: str = "",
) -> dict[str, Any]:
    """Build a role prompt payload without constructing an orchestrator."""

    return _PAYLOAD_BUILDER._build_role_prompt_payload(enriched_payload, role_name=role_name)


def build_trip_request_payload(request: PlanningRequest) -> dict[str, Any]:
    """Build the credential-free trip payload shared by all orchestrators."""

    payload: dict[str, Any] = {
        "trip_id": request.trip_id,
        "title": request.title,
        "origin": request.origin,
        "destination": request.destination,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "trip_days": max(1, (request.end_date - request.start_date).days + 1),
        "budget": request.budget,
        "travelers": request.travelers,
        "interests": list(request.interests),
        "accommodation_preference": request.accommodation_preference,
        "pace": request.pace,
        "transport_mode": request.transport_mode,
    }
    generated_at = request.planning_generated_at
    if generated_at is not None:
        local_generated_at = generated_at.astimezone() if generated_at.tzinfo is not None else generated_at
        earliest = local_generated_at.replace(second=0, microsecond=0) + timedelta(minutes=30)
        payload.update(
            {
                "planning_generated_at": local_generated_at.isoformat(timespec="minutes"),
                "current_local_date": local_generated_at.date().isoformat(),
                "current_local_time": local_generated_at.strftime("%H:%M"),
                "same_day_earliest_start_time": (
                    earliest.strftime("%H:%M") if request.start_date == local_generated_at.date() else None
                ),
            }
        )
    return payload
