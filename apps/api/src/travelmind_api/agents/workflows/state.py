import hashlib
import json
from typing import Any, TypedDict
from urllib.parse import urlparse

from travelmind_api.services.llm.config import LlmEndpointConfig


TRIP_GENERATION_GRAPH_VERSION = "trip-generation.v1"
TRIP_GENERATION_STATE_SCHEMA_VERSION = 1


class TripGenerationState(TypedDict, total=False):
    run_id: str
    graph_version: str
    schema_version: int
    input_fingerprint: str
    output_locale: str
    trip_request: dict[str, Any]
    planning_brief: dict[str, Any]
    role_results: dict[str, dict[str, Any]]


def non_sensitive_model_identity(endpoint: LlmEndpointConfig) -> dict[str, str]:
    return {
        "provider_protocol": endpoint.provider_protocol,
        "wire_api": endpoint.wire_api,
        "model": endpoint.model,
        "endpoint_host": urlparse(endpoint.base_url).netloc or endpoint.base_url,
    }


def build_input_fingerprint(
    *,
    trip_request: dict[str, Any],
    output_locale: str,
    prompt_versions: dict[str, str],
    model_identities: dict[str, dict[str, str]],
) -> str:
    canonical = json.dumps(
        {
            "graph_version": TRIP_GENERATION_GRAPH_VERSION,
            "schema_version": TRIP_GENERATION_STATE_SCHEMA_VERSION,
            "trip_request": trip_request,
            "output_locale": output_locale,
            "prompt_versions": prompt_versions,
            "model_identities": model_identities,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
