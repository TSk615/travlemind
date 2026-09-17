from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from travelmind_api.services.entity_identity import normalize_identity
from travelmind_api.services.search_connector import ConfiguredSearchGateway, is_public_source_url


def verify_transport_candidate_pages(transport, search_config):
    """Classify timetable evidence without treating extractor failure as contradiction."""
    result = transport.model_copy(deep=True)
    candidates = list(result.service_candidates)
    if not candidates:
        return result

    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    public_candidates = [row for row in candidates if is_public_source_url(row.source_url)]
    invalid_candidates = [row for row in candidates if row not in public_candidates]
    if search_config is None:
        result.service_candidates = [
            _with_evidence(row, "referenced", checked_at, "班次字段和来源已保留，但未配置正文核验服务。")
            for row in public_candidates
        ]
        if invalid_candidates:
            result.notes = _add_note(result.notes, "已停用没有公共来源页面的候选班次。")
        result.notes = _add_note(result.notes, "班次来源尚未完成正文复核，当前仅作待确认的静态参考。")
        return result

    gateway = ConfiguredSearchGateway(search_config)
    urls = list(dict.fromkeys(row.source_url for row in public_candidates))[:8]
    pages: dict[str, dict] = {}
    extraction_failed = False
    if urls:
        try:
            response = gateway.call_operation("extract", {"urls": urls})
            pages = {
                _url_key(str(row.get("url") or "")): row
                for row in response.get("results", [])
                if isinstance(row, dict) and str(row.get("url") or "").strip()
            }
        except Exception:
            extraction_failed = True

    verified = []
    unresolved = []
    original_conflicts: set[str] = set()
    for candidate in public_candidates:
        text = _page_text(pages.get(_url_key(candidate.source_url)))
        if text and _candidate_tuple_supported(candidate, text):
            verified.append(_with_evidence(candidate, "verified", checked_at, "来源正文同一记录支持车次、站点和发到时刻。"))
            continue
        if text and _candidate_tuple_conflicted(candidate, text):
            original_conflicts.add(_candidate_key(candidate))
        unresolved.append(candidate)

    # Aggregate route pages are allowed. If a row cannot be located, search a
    # service page using identifiers only; proposed times are deliberately not
    # included in the query to avoid confirmation bias.
    fallback_urls: dict[str, list[str]] = {}
    for candidate in unresolved:
        try:
            search = gateway.call_operation("search", {
                "query": f"{candidate.service_number} {candidate.origin} {candidate.destination} 车次时刻表",
                "num_results": 4,
                "include_images": False,
            })
        except Exception:
            continue
        service_pattern = re.compile(
            rf"(?<![0-9a-z]){re.escape(candidate.service_number)}(?![0-9a-z])", re.I,
        )
        for row in search.get("results", []):
            if not isinstance(row, dict):
                continue
            url = str(row.get("url") or "").strip()
            search_text = " ".join([str(row.get("title") or ""), str(row.get("content") or "")])
            if is_public_source_url(url) and service_pattern.search(search_text):
                fallback_urls.setdefault(_candidate_key(candidate), []).append(url)

    detail_urls = list(dict.fromkeys(
        url for urls_for_service in fallback_urls.values() for url in urls_for_service
    ))[:16]
    detail_pages: dict[str, dict] = {}
    if detail_urls:
        try:
            detail_response = gateway.call_operation("extract", {"urls": detail_urls})
            detail_pages = {
                _url_key(str(row.get("url") or "")): row
                for row in detail_response.get("results", [])
                if isinstance(row, dict) and str(row.get("url") or "").strip()
            }
        except Exception:
            extraction_failed = True

    recovered = []
    referenced = []
    conflicted = []
    for candidate in unresolved:
        key = _candidate_key(candidate)
        detail_conflict = False
        for url in fallback_urls.get(key, []):
            text = _page_text(detail_pages.get(_url_key(url)))
            if text and _candidate_tuple_supported(candidate, text):
                recovered.append(_with_evidence(
                    candidate.model_copy(update={"source_url": url}), "verified", checked_at,
                    "线路页未能定位字段，单班次页面同一记录支持车次、站点和发到时刻。",
                ))
                break
            detail_conflict = detail_conflict or bool(text and _candidate_tuple_conflicted(candidate, text))
        else:
            if key in original_conflicts or detail_conflict:
                conflicted.append(candidate)
            else:
                reason = (
                    "来源正文抓取失败；班次字段完整且有来源，暂作待确认参考。"
                    if extraction_failed or not pages
                    else "来源页面未能解析出同一条班次记录；字段暂作待确认参考。"
                )
                referenced.append(_with_evidence(candidate, "referenced", checked_at, reason))

    result.service_candidates = [*verified, *recovered, *referenced]
    if recovered:
        names = "、".join(dict.fromkeys(row.service_number for row in recovered))
        result.notes = _add_note(result.notes, f"已通过单班次页面补充核验：{names}。")
    if referenced:
        names = "、".join(dict.fromkeys(row.service_number for row in referenced))
        result.notes = _add_note(result.notes, f"正文未能完成逐字段复核，以下班次保留为待确认参考：{names}。")
    if conflicted:
        names = "、".join(dict.fromkeys(row.service_number for row in conflicted))
        result.notes = _add_note(result.notes, f"来源正文存在明确站点或时刻冲突，已停用候选：{names}。")
    if invalid_candidates:
        result.notes = _add_note(result.notes, "已停用没有公共来源页面的候选班次。")
    return result


def _with_evidence(candidate, status: str, checked_at: str, reason: str):
    note = "正文已复核。" if status == "verified" else "正文待复核，实际运行与余票须在购票前确认。"
    return candidate.model_copy(update={
        "evidence_status": status,
        "evidence_checked_at": checked_at,
        "evidence_reason": reason,
        "schedule_checked_at": checked_at,
        "notes": list(dict.fromkeys([*candidate.notes, note])),
    })


def _add_note(notes: list[str], note: str) -> list[str]:
    return list(dict.fromkeys([*notes, note]))


def _page_text(page) -> str:
    if not isinstance(page, dict):
        return ""
    return "\n".join([str(page.get("title") or ""), str(page.get("raw_content") or page.get("content") or "")])


def _candidate_tuple_supported(candidate, text: str) -> bool:
    expected = (
        normalize_identity(candidate.origin), normalize_identity(candidate.destination),
        normalize_identity(candidate.departure_time), normalize_identity(candidate.arrival_time),
    )
    return any(all(value and value in normalize_identity(window) for value in expected)
               for window in _candidate_row_windows(candidate, text))


def _candidate_tuple_conflicted(candidate, text: str) -> bool:
    origin = normalize_identity(candidate.origin)
    destination = normalize_identity(candidate.destination)
    expected = (origin, destination, normalize_identity(candidate.departure_time), normalize_identity(candidate.arrival_time))
    for window in _candidate_row_windows(candidate, text):
        normalized = normalize_identity(window)
        clocks = re.findall(r"(?<!\d)(?:[01]?\d|2[0-3])[:：][0-5]\d(?!\d)", window)
        endpoints_seen = sum(value in normalized for value in (origin, destination) if value)
        if endpoints_seen and len(clocks) >= 2 and not all(value and value in normalized for value in expected):
            return True
    return False


def _candidate_row_windows(candidate, text: str) -> list[str]:
    raw = str(text or "").casefold()
    service = str(candidate.service_number or "").strip().casefold()
    if not raw or not service:
        return []
    exact = re.compile(rf"(?<![0-9a-z]){re.escape(service)}(?![0-9a-z])", re.I)
    any_service = re.compile(r"(?<![0-9a-z])[gdzktc]\d{1,5}(?![0-9a-z])", re.I)
    windows = [line for line in raw.splitlines() if exact.search(line) and len(any_service.findall(line)) == 1]
    flattened = re.sub(r"\s+", " ", raw)
    matches = list(any_service.finditer(flattened))
    for index, match in enumerate(matches):
        if match.group(0).casefold() != service:
            continue
        start = max(0, matches[index - 1].end() if index else match.start() - 100)
        end = min(len(flattened), matches[index + 1].start() if index + 1 < len(matches) else match.end() + 220)
        windows.append(flattened[start:end])
    return windows


def _candidate_key(candidate) -> str:
    return "|".join([str(candidate.scope), str(candidate.service_number).casefold(), str(candidate.departure_date), str(candidate.origin), str(candidate.destination)])


def _url_key(value: str) -> str:
    try:
        parts = urlsplit(str(value or "").strip())
    except ValueError:
        return str(value or "").strip().casefold().rstrip("/")
    return urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path.rstrip("/"), parts.query, ""))
