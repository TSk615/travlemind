import hashlib
import json
from typing import Annotated, Any, TypedDict
from urllib.parse import urlparse

from travelmind_api.services.llm.config import LlmEndpointConfig


TRIP_GENERATION_GRAPH_VERSION = "trip-generation.v1"
TRIP_GENERATION_STATE_SCHEMA_VERSION = 1
TRIP_REFINEMENT_GRAPH_VERSION = "trip-refinement.v1"
TRIP_REFINEMENT_STATE_SCHEMA_VERSION = 1


def merge_state_mappings(
    left: dict[str, dict[str, Any]],
    right: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    return {**(left or {}), **(right or {})}


class TripGenerationState(TypedDict, total=False):
    run_id: str
    graph_version: str
    schema_version: int
    input_fingerprint: str
    output_locale: str
    trip_request: dict[str, Any]
    planning_brief: dict[str, Any]
    role_results: Annotated[dict[str, dict[str, Any]], merge_state_mappings]
    poi_payload: dict[str, Any]
    weather_payload: dict[str, Any]
    hotel_payload: dict[str, Any]
    transport_payload: dict[str, Any]
    planner_payload: dict[str, Any]
    poi_grounding: dict[str, Any]
    weather_guidance: dict[str, Any]
    poi_collection: dict[str, Any]
    hotel_recommendation: dict[str, Any]
    transport_guidance: dict[str, Any]
    final_payload: dict[str, Any]
    validation_errors: list[str]
    repair_count: int
    agent_runs: list[dict[str, Any]]
    pipeline_notes: list[str]
    weather_citations: list[str]
    weather_tool_results: dict[str, Any]
    grounding_documents: list[dict[str, Any]]
    planning_result: dict[str, Any]


class TripRefinementState(TypedDict, total=False):
    run_id: str
    graph_version: str
    schema_version: int
    input_fingerprint: str
    trip_request: dict[str, Any]
    current_plan: dict[str, Any]
    refinement_context: dict[str, Any]
    instruction: str
    scope: str
    day_index: int | None
    affected_evidence: list[str]
    refiner_payload: dict[str, Any]
    final_payload: dict[str, Any]
    validation_errors: list[str]
    repair_count: int
    role_results: Annotated[dict[str, dict[str, Any]], merge_state_mappings]
    planning_result: dict[str, Any]


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
