from datetime import datetime, timezone

from travelmind_api.services.entity_identity import entity_matches, normalize_identity
from travelmind_api.services.search_connector import ConfiguredSearchGateway, is_public_source_url


def verify_hotel_pages(hotel, search_config):
    """Fetched evidence is separate from the specialist's self-reported titles."""
    result = hotel.model_copy(deep=True)
    candidates = [c for c in [result.final_recommended_hotel, *result.hotel_candidates] if c]
    for candidate in candidates:
        candidate.identity_status = "unverified"
        candidate.verified_source_urls = []
        candidate.identity_checked_at = None
        candidate.evidence_notes = ["房价与可订状态未独立核验；页面实体核验不等于实时可订。"]
    if search_config is None:
        return result
    urls = list(dict.fromkeys(url for c in candidates for url in c.source_urls if is_public_source_url(url)))[:8]
    if not urls:
        return result
    try:
        response = ConfiguredSearchGateway(search_config).call_operation("extract", {"urls": urls})
    except Exception:
        for candidate in candidates:
            candidate.evidence_notes.append("来源抓取失败，保留为待核验候选。")
        return result
    pages = {row.get("url"): row for row in response.get("results", []) if isinstance(row, dict)}
    checked_at = datetime.now(timezone.utc).isoformat()
    for candidate in candidates:
        actual_titles: list[str] = []
        for url in candidate.source_urls:
            page = pages.get(url)
            if not page:
                actual_titles.append("")
                continue
            title = str(page.get("title") or "")
            actual_titles.append(title)
            content = str(page.get("raw_content") or page.get("content") or "")
            # Exact local entity and city must appear in independently fetched
            # content; a generic roundup mentioning a name alone is insufficient.
            name_ok = entity_matches(candidate.name, title) or entity_matches(candidate.name, content[:1500])
            city_ok = entity_matches(candidate.city, title + content)
            address = normalize_identity(candidate.address)
            address_ok = len(address) >= 5 and address not in {"unknown", "未知"} and address in normalize_identity(content)
            if name_ok and city_ok and (address_ok or entity_matches(candidate.name, title)):
                candidate.verified_source_urls.append(url)
        # Replace self-reported titles with what the independent fetch
        # actually returned. Empty entries intentionally remain empty so the
        # audit layer never treats a model-authored title as fetched evidence.
        candidate.source_page_titles = actual_titles
        if candidate.verified_source_urls:
            candidate.identity_status = "page_verified"
            candidate.identity_checked_at = checked_at
            candidate.evidence_notes.append(
                f"已于 {checked_at} 独立核对 {len(candidate.verified_source_urls)} 个酒店详情来源；仅确认页面实体，不代表实时可订。"
            )
        else:
            candidate.evidence_notes.append("未抓取到可确认名称、城市及地址/页面实体的一致证据。")
    return result
