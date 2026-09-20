from __future__ import annotations

import re
from datetime import date, timedelta
from urllib.parse import urlparse

from travelmind_api.services.entity_identity import entity_matches
from travelmind_api.services.execution_validation import has_closed_weekday_constraint
from travelmind_api.services.search_connector import ConfiguredSearchGateway, is_public_source_url


_WEEKDAY_NAMES = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
_HOLIDAY_EXCEPTION_PATTERN = re.compile(
    r"(?:除)?法定节假日(?:外|除外|正常开放)|(?:除)?节假日(?:外|除外|正常开放)|"
    r"except(?:ing)?\s+(?:statutory\s+|public\s+)?holidays?",
    re.I,
)
_COMMUNITY_OR_AGGREGATOR_DOMAINS = (
    "amap.com", "baidu.com", "ctrip.com", "dianping.com", "douyin.com",
    "mafengwo.cn", "qunar.com", "sohu.com", "trip.com", "weibo.com", "xiaohongshu.com", "zhihu.com",
)
_OPERATION_SENSITIVE_TERMS = (
    "博物馆", "博物院", "美术馆", "纪念馆", "展览馆", "科技馆", "天文馆",
    "故居", "王府", "宫", "寺", "庙", "塔", "钟楼", "鼓楼", "城楼",
)

# Many museum notices say statutory holidays are excluded from weekly closure.
# For years not listed here, keep the caveat but do not create a hard conflict.
_CHINA_PUBLIC_HOLIDAY_RANGES: dict[int, tuple[tuple[int, int, int, int], ...]] = {
    2026: (
        (1, 1, 1, 3),
        (2, 15, 2, 23),
        (4, 4, 4, 6),
        (5, 1, 5, 5),
        (6, 19, 6, 21),
        (9, 25, 9, 27),
        (10, 1, 10, 7),
    ),
}


def verify_poi_open_days(poi_grounding, *, start_date: date, end_date: date, search_config):
    """Attach explicit closed-day evidence from cited and targeted official pages.

    Guide sources remain useful for discovery. For closure-sensitive named
    venues that only cite guide/aggregator pages, perform a small targeted
    official-page lookup so weekly closure rules can reach both the planner and
    the execution validator.
    """
    result = poi_grounding.model_copy(deep=True)
    if search_config is None or not result.featured_pois:
        return result

    gateway = ConfiguredSearchGateway(search_config)
    discovered_urls = _discover_official_operation_urls(result.featured_pois, gateway, limit=6)
    for poi in result.featured_pois:
        official_url = discovered_urls.get(poi.name)
        if official_url:
            poi.source_urls = _append_unique(poi.source_urls, official_url)

    selected_urls = _select_source_urls(result.featured_pois, limit=24)
    if not selected_urls:
        return result

    pages: dict[str, str] = {}
    for offset in range(0, len(selected_urls), 8):
        try:
            response = gateway.call_operation("extract", {"urls": selected_urls[offset:offset + 8]})
        except Exception:
            continue
        for row in response.get("results", []):
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            if not url:
                continue
            pages[_url_key(url)] = "\n".join([
                str(row.get("title") or ""),
                str(row.get("raw_content") or row.get("content") or ""),
            ])

    trip_dates = _date_range(start_date, end_date)
    for poi in result.featured_pois:
        public_urls = [url for url in _poi_source_urls(poi) if is_public_source_url(url)]
        for url in public_urls:
            text = pages.get(_url_key(url), "")
            if not text or not entity_matches(poi.name, text):
                continue
            exception_applies = bool(_HOLIDAY_EXCEPTION_PATTERN.search(text))
            for target_date in trip_dates:
                if not has_closed_weekday_constraint(text, target_date.weekday()):
                    continue
                holiday_status = _known_china_public_holiday(target_date)
                if exception_applies and holiday_status is True:
                    continue
                if exception_applies and holiday_status is None:
                    poi.caveats = _append_unique(
                        poi.caveats,
                        f"开放信息注明{_WEEKDAY_NAMES[target_date.weekday()]}闭馆，但法定节假日除外；"
                        f"{target_date.isoformat()} 的节假日状态尚未内置核对。",
                    )
                    continue
                poi.evidence_notes = _append_unique(
                    poi.evidence_notes,
                    f"开放日来源复核：{target_date.isoformat()}（{_WEEKDAY_NAMES[target_date.weekday()]}）"
                    f"落在{_WEEKDAY_NAMES[target_date.weekday()]}闭馆规则内。来源：{url}",
                )

    return result


def _discover_official_operation_urls(pois, gateway, *, limit: int) -> dict[str, str]:
    discovered: dict[str, str] = {}
    candidates = [
        poi for poi in pois
        if _is_operation_sensitive(poi) and not any(_is_officialish_url(url) for url in _poi_source_urls(poi))
    ][:limit]
    for poi in candidates:
        try:
            response = gateway.call_operation("search", {
                "query": f'"{poi.name}" 官方 开放时间 闭馆',
                "num_results": 5,
                "include_images": False,
            })
        except Exception:
            continue
        ranked: list[tuple[int, int, str]] = []
        for index, row in enumerate(response.get("results", [])):
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            text = "\n".join([str(row.get("title") or ""), str(row.get("content") or "")])
            if not is_public_source_url(url) or not entity_matches(poi.name, text):
                continue
            ranked.append((_official_url_score(url), index, url))
        if ranked:
            ranked.sort(key=lambda row: (row[0], row[1]))
            discovered[poi.name] = ranked[0][2]
    return discovered


def _is_operation_sensitive(poi) -> bool:
    text = " ".join([
        str(getattr(poi, "name", "") or ""),
        str(getattr(poi, "category", "") or ""),
        str(getattr(poi, "reason", "") or ""),
    ])
    return any(term in text for term in _OPERATION_SENSITIVE_TERMS)


def _is_officialish_url(url: str) -> bool:
    return _official_url_score(url) <= 1


def _official_url_score(url: str) -> int:
    host = (urlparse(url).hostname or "").casefold()
    if host.endswith(".gov.cn") or host == "gov.cn":
        return 0
    if host.endswith((".org.cn", ".edu.cn")):
        return 1
    if any(host == domain or host.endswith(f".{domain}") for domain in _COMMUNITY_OR_AGGREGATOR_DOMAINS):
        return 4
    if host.endswith(".cn"):
        return 2
    return 3


def _select_source_urls(pois, *, limit: int) -> list[str]:
    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for poi_index, poi in enumerate(pois):
        for source_index, url in enumerate(_poi_source_urls(poi)):
            if not is_public_source_url(url):
                continue
            key = _url_key(url)
            if key in seen:
                continue
            seen.add(key)
            host = (urlparse(url).hostname or "").casefold()
            source_class = 1 if any(
                host == domain or host.endswith(f".{domain}")
                for domain in _COMMUNITY_OR_AGGREGATOR_DOMAINS
            ) else 0
            ranked.append((source_class, source_index + poi_index, url))
    ranked.sort(key=lambda row: (row[0], row[1]))
    return [row[2] for row in ranked[:limit]]


def _poi_source_urls(poi) -> list[str]:
    booking_urls = poi.booking_info.source_urls if poi.booking_info is not None else []
    return list(dict.fromkeys([
        *[str(url).strip() for url in poi.source_urls if str(url).strip()],
        *[str(url).strip() for url in booking_urls if str(url).strip()],
    ]))


def _date_range(start_date: date, end_date: date) -> list[date]:
    if end_date < start_date:
        return []
    return [start_date + timedelta(days=offset) for offset in range((end_date - start_date).days + 1)]


def _known_china_public_holiday(value: date) -> bool | None:
    ranges = _CHINA_PUBLIC_HOLIDAY_RANGES.get(value.year)
    if ranges is None:
        return None
    return any(
        date(value.year, start_month, start_day) <= value <= date(value.year, end_month, end_day)
        for start_month, start_day, end_month, end_day in ranges
    )


def _append_unique(values: list[str], value: str) -> list[str]:
    return list(dict.fromkeys([*values, value]))


def _url_key(value: str) -> str:
    return str(value or "").strip().rstrip("/").casefold()
