from __future__ import annotations

import os

from travelmind_api.services.maps.base import MapsPoiProvider
from travelmind_api.services.maps.stub import StubMapsPoiProvider


def build_maps_provider(provider_name: str | None = None) -> MapsPoiProvider:
    selected_provider = (provider_name or os.getenv("TRAVELMIND_MAPS_PROVIDER", "stub")).strip().lower()
    if selected_provider == "stub":
        return StubMapsPoiProvider()
    return StubMapsPoiProvider()