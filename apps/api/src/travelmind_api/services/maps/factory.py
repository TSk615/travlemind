from __future__ import annotations

import os

from travelmind_api.services.maps.base import MapsPoiProvider
from travelmind_api.services.maps.amap import AmapMapsPoiProvider
from travelmind_api.services.maps.stub import StubMapsPoiProvider


def build_maps_provider(provider_name: str | None = None) -> MapsPoiProvider:
    selected_provider = (provider_name or os.getenv("TRAVELMIND_MAPS_PROVIDER", "stub")).strip().lower()
    if selected_provider == "stub":
        return StubMapsPoiProvider()
    if selected_provider in {"amap", "gaode"}:
        api_key = os.getenv("TRAVELMIND_AMAP_API_KEY", "").strip()
        if not api_key:
            raise ValueError("TRAVELMIND_AMAP_API_KEY is required when TRAVELMIND_MAPS_PROVIDER=amap.")
        base_url = os.getenv("TRAVELMIND_AMAP_BASE_URL", "https://restapi.amap.com").strip() or "https://restapi.amap.com"
        timeout_seconds = _float_env("TRAVELMIND_AMAP_TIMEOUT_SECONDS", 8.0)
        return AmapMapsPoiProvider(api_key=api_key, base_url=base_url, timeout_seconds=timeout_seconds)
    raise ValueError(f"Unsupported maps provider: {selected_provider}")


def _float_env(name: str, default: float) -> float:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return default
    try:
        return float(raw_value)
    except ValueError:
        return default
