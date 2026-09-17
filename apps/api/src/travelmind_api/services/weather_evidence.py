from __future__ import annotations

import re
from datetime import date, datetime

from travelmind_api.services.entity_identity import normalize_identity
from travelmind_api.services.search_connector import ConfiguredSearchGateway, is_public_source_url


_CONDITION_PATTERN = re.compile(
    r"雷阵雨|阵雨|暴雨|大雨|中雨|小雨|雨夹雪|大雪|中雪|小雪|多云|阴|晴|雾|霾|雨|雪"
)
_EVIDENCE_FIELDS = (
    "condition", "temperature_min_c", "temperature_max_c", "precipitation_probability", "wind",
)


def verify_daily_forecast_pages(weather, search_config):
    """Verify weather per field; an unavailable extractor is not a contradiction."""
    result = weather.model_copy(deep=True)
    forecasts = list(result.daily_forecasts)
    if not forecasts:
        return result

    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    urls = list(dict.fromkeys(
        url for forecast in forecasts for url in forecast.source_urls if is_public_source_url(url)
    ))[:8]
    pages: dict[str, str] = {}
    extraction_failed = search_config is None
    if search_config is not None and urls:
        try:
            response = ConfiguredSearchGateway(search_config).call_operation("extract", {"urls": urls})
            for row in response.get("results", []):
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if url:
                    pages[_url_key(url)] = "\n".join([
                        str(row.get("title") or ""),
                        str(row.get("raw_content") or row.get("content") or ""),
                    ])
        except Exception:
            extraction_failed = True

    for forecast in forecasts:
        forecast.evidence_checked_at = checked_at
        public_urls = list(dict.fromkeys(url for url in forecast.source_urls if is_public_source_url(url)))
        forecast.source_urls = public_urls
        forecast.field_evidence = {field: "unknown" for field in _EVIDENCE_FIELDS}
        if not public_urls:
            _clear_forecast(forecast, "没有可访问的逐日来源，已清空不可追溯字段。")
            continue
        if forecast.forecast_type == "seasonal_reference":
            for field in _EVIDENCE_FIELDS:
                if str(getattr(forecast, field) or "").strip():
                    forecast.field_evidence[field] = "referenced"
            forecast.evidence_status = "referenced"
            forecast.evidence_reason = "该日期超出可靠逐日预报范围，仅保留季节性来源参考。"
            forecast.outlook = _build_outlook(forecast)
            continue

        windows = [
            window
            for url in public_urls
            for window in _date_windows(pages.get(_url_key(url), ""), forecast.date)
        ]
        if not windows:
            # Date-bound values with a source remain useful when a JS page,
            # anti-bot response or extractor limitation hides the row.
            for field in _EVIDENCE_FIELDS:
                if str(getattr(forecast, field) or "").strip():
                    forecast.field_evidence[field] = "referenced"
            forecast.evidence_status = "referenced"
            forecast.evidence_reason = (
                "来源正文抓取失败，日期完整的逐日字段暂作参考。"
                if extraction_failed or not pages
                else "来源页面未解析出对应日期区块，逐日字段暂作参考。"
            )
            forecast.risk = _append_note(forecast.risk, "天气字段有来源但正文待复核，出发前请刷新。")
            forecast.outlook = _build_outlook(forecast)
            continue

        field_statuses = {
            "condition": _condition_evidence(windows, forecast.condition),
            "temperature_min_c": _temperature_evidence(windows, forecast.temperature_min_c),
            "temperature_max_c": _temperature_evidence(windows, forecast.temperature_max_c),
            "precipitation_probability": _text_field_evidence(
                windows, forecast.precipitation_probability, r"\d{1,3}\s*%"
            ),
            "wind": _wind_evidence(windows, forecast.wind),
        }
        forecast.field_evidence = field_statuses
        conflicted_fields = []
        for field, status in field_statuses.items():
            if status == "conflicted":
                setattr(forecast, field, "")
                conflicted_fields.append(field)
        core = [field_statuses[name] for name in ("condition", "temperature_min_c", "temperature_max_c")]
        if "conflicted" in core:
            forecast.evidence_status = "conflicted"
            forecast.evidence_reason = "来源对应日期区块与部分核心天气字段明确冲突；冲突字段已清空。"
        elif all(status == "verified" for status in core):
            forecast.evidence_status = "verified"
            forecast.evidence_reason = "来源对应日期区块支持天气现象和最高/最低温度。"
        else:
            forecast.evidence_status = "referenced"
            forecast.evidence_reason = "来源支持该日期，但部分字段未能从正文独立解析，仍按参考信息展示。"
        if conflicted_fields:
            labels = {"condition": "天气现象", "temperature_min_c": "最低温", "temperature_max_c": "最高温", "precipitation_probability": "降水概率", "wind": "风力"}
            forecast.risk = _append_note(forecast.risk, f"来源与{'、'.join(labels[name] for name in conflicted_fields)}冲突，相关字段已留空。")
        forecast.outlook = _build_outlook(forecast)
        allowed_conditions = [forecast.condition] if forecast.condition else []
        allowed_temperatures = [forecast.temperature_min_c, forecast.temperature_max_c]
        if has_unsupported_weather_condition(forecast.risk, allowed_conditions) or _has_unsupported_temperature_claim(forecast.risk, allowed_temperatures):
            forecast.risk = ""

    result.source_urls = list(dict.fromkeys(url for forecast in forecasts for url in forecast.source_urls))
    result.daily_outlook = [f"{forecast.date.isoformat()}：{_build_outlook(forecast)}" for forecast in forecasts]
    retained_conditions = [forecast.condition for forecast in forecasts if forecast.condition]
    retained_temperatures = [
        value for forecast in forecasts for value in (forecast.temperature_min_c, forecast.temperature_max_c) if value
    ]
    result.weather_risks = [
        risk for risk in result.weather_risks
        if not has_unsupported_weather_condition(risk, retained_conditions)
        and not _has_unsupported_temperature_claim(risk, retained_temperatures)
    ]
    # Segment prose often repeats rejected precise values. Keep its advice but
    # rebuild factual weather prose from the final daily fields.
    for segment in result.segments:
        segment.outlook = "逐日天气以对应日期卡片中的最终字段为准。"
        segment.temperature_range = ""
        segment.risks = [
            risk for risk in segment.risks
            if not has_unsupported_weather_condition(risk, retained_conditions)
            and not _has_unsupported_temperature_claim(risk, retained_temperatures)
        ]

    counts = {status: sum(row.evidence_status == status for row in forecasts)
              for status in ("verified", "referenced", "conflicted", "unknown")}
    if counts["verified"] == len(forecasts):
        result.overall_outlook = "全部日期的天气现象和最高/最低温度已通过来源正文复核；缺失字段不作推算。"
    elif counts["verified"]:
        result.overall_outlook = f"{counts['verified']}天已完成正文复核，其余日期按有来源参考展示；出发前请刷新天气。"
    elif counts["referenced"]:
        result.overall_outlook = "逐日天气均保留了日期与来源，但正文尚未完成独立复核；当前可作规划参考，出发前请刷新。"
    else:
        result.overall_outlook = "当前没有可用的逐日天气字段，出发前请刷新天气。"
    return result


def _condition_evidence(windows: list[str], value: str) -> str:
    expected = set(_CONDITION_PATTERN.findall(str(value or "")))
    if not expected:
        return "unknown"
    source_sets = [set(_CONDITION_PATTERN.findall(window)) for window in windows]
    source_sets = [tokens for tokens in source_sets if tokens]
    if not source_sets:
        return "referenced"
    # Multiple providers may describe the same day differently. One coherent
    # date window that supports the proposed condition is enough to verify it;
    # only mark a conflict when every parseable date window disagrees.
    return "verified" if any(expected == tokens for tokens in source_sets) else "conflicted"


def _temperature_evidence(windows: list[str], value: str) -> str:
    expected = str(value or "").strip()
    if not expected:
        return "unknown"
    numbers = set()
    for window in windows:
        for first, second in re.findall(r"(-?\d{1,2})\s*[/~～至—-]\s*(-?\d{1,2})\s*(?:℃|°\s*[cC])", window):
            numbers.update((first, second))
        numbers.update(re.findall(r"(-?\d{1,2})\s*(?:℃|°\s*[cC])", window))
    if not numbers:
        return "referenced"
    return "verified" if expected in numbers else "conflicted"


def _text_field_evidence(windows: list[str], value: str, signal_pattern: str) -> str:
    expected = normalize_identity(value)
    if not expected:
        return "unknown"
    if any(expected in normalize_identity(window) for window in windows):
        return "verified"
    return "conflicted" if any(re.search(signal_pattern, window) for window in windows) else "referenced"


def _wind_evidence(windows: list[str], value: str) -> str:
    if not str(value or "").strip():
        return "unknown"
    if any(_supports_wind(window, value) for window in windows):
        return "verified"
    wind_signal = re.compile(r"(?:东北|东南|西北|西南|东|南|西|北)风|\d+\s*[-~至]?\s*\d*\s*级")
    return "conflicted" if any(wind_signal.search(window) for window in windows) else "referenced"


def _supports_wind(window: str, wind: str) -> bool:
    normalized_window = normalize_identity(window)
    directions = re.findall(r"(?:东北|东南|西北|西南|东|南|西|北)风", str(wind or ""))
    if directions and not all(normalize_identity(direction) in normalized_window for direction in directions):
        return False
    levels = re.findall(r"\d+", str(wind or ""))
    return not levels or all(level in re.findall(r"\d+", window) for level in levels)


def _build_outlook(forecast) -> str:
    parts = []
    if str(forecast.condition or "").strip():
        parts.append(str(forecast.condition).strip())
    low, high = str(forecast.temperature_min_c or "").strip(), str(forecast.temperature_max_c or "").strip()
    if low and high:
        parts.append(f"{low}～{high}℃")
    elif low:
        parts.append(f"最低{low}℃")
    elif high:
        parts.append(f"最高{high}℃")
    if str(forecast.precipitation_probability or "").strip():
        parts.append(f"降水概率{forecast.precipitation_probability}")
    if str(forecast.wind or "").strip():
        parts.append(str(forecast.wind).strip())
    return "，".join(parts) + ("。" if parts else "暂无可用逐日字段，出发前请刷新。")


def _clear_forecast(forecast, reason: str) -> None:
    forecast.forecast_type = "unknown"
    for field in _EVIDENCE_FIELDS:
        setattr(forecast, field, "")
    forecast.evidence_status = "unknown"
    forecast.evidence_reason = reason
    forecast.outlook = "暂无可追溯的逐日预报，出发前请刷新天气。"
    forecast.risk = _append_note(forecast.risk, reason)


def _date_windows(text: str, target: date) -> list[str]:
    raw = str(text or "")
    if not raw:
        return []
    month, day = target.month, target.day
    patterns = (
        rf"{target.year}\s*[-/.年]\s*0?{month}\s*[-/.月]\s*0?{day}(?:\s*日)?",
        rf"(?<!\d)0?{month}\s*[-/.月]\s*0?{day}(?:\s*日)?(?!\d)",
    )
    windows = []
    lines = raw.splitlines()
    for index, line in enumerate(lines):
        if any(re.search(pattern, line) for pattern in patterns):
            end = min(len(lines), index + 9)
            next_date = r"(?<!\d)(?:0?[1-9]|1[0-2])\s*(?:[-/.]|月)\s*(?:0?[1-9]|[12]\d|3[01])(?:\s*日)?(?!\d)"
            for candidate_index in range(index + 1, end):
                if re.search(next_date, lines[candidate_index]):
                    end = candidate_index
                    break
            windows.append(" ".join(lines[index:end]))
    if windows:
        return windows
    for pattern in patterns:
        for match in re.finditer(pattern, raw):
            windows.append(raw[max(0, match.start() - 40):match.end() + 180])
    return windows


def _append_note(original: str, note: str) -> str:
    base = str(original or "").strip().rstrip("。")
    return f"{base}；{note}" if base else note


def _url_key(value: str) -> str:
    return str(value or "").strip().casefold().rstrip("/")


def _has_unsupported_temperature_claim(claim: str, retained_temperatures: list[str]) -> bool:
    claimed = set(re.findall(r"(-?\d{1,2})\s*(?:℃|°\s*[cC])", str(claim or "")))
    allowed = {str(value).strip() for value in retained_temperatures if str(value).strip()}
    return bool(claimed and not claimed.issubset(allowed))


def has_unsupported_weather_condition(claim: str, verified_conditions: list[str]) -> bool:
    claimed = set(_CONDITION_PATTERN.findall(str(claim or "")))
    if not claimed:
        return False
    allowed = {token for condition in verified_conditions for token in _CONDITION_PATTERN.findall(str(condition or ""))}
    return not claimed.issubset(allowed)
