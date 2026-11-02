"""Reject empty research before spending a planner request; never invent POIs."""
from collections.abc import Mapping
from typing import Any


class PoiResearchUnavailableError(ValueError):
    code = "poi_research_unavailable"

    def __init__(self):
        super().__init__("暂时没有取得可用的景点资料，已停止生成以避免给出空白行程，请稍后重试。")


def ensure_usable_poi_research(grounding: Any) -> None:
    def field(obj, name):
        return obj.get(name) if isinstance(obj, Mapping) else getattr(obj, name, None)
    candidates = [*(field(grounding, "top_pois") or []), *(field(grounding, "featured_pois") or [])]
    if not any(str(field(item, "name") or "").strip() for item in candidates):
        raise PoiResearchUnavailableError()
