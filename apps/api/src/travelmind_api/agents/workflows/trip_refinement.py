from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from travelmind_api.agents.base import PlanningRequest, PlanningResult, RefinementContext
from travelmind_api.agents.workflows.state import (
    TRIP_REFINEMENT_GRAPH_VERSION,
    TRIP_REFINEMENT_STATE_SCHEMA_VERSION,
    TripRefinementState,
    non_sensitive_model_identity,
)
from travelmind_api.services.llm.config import LlmEndpointConfig
from travelmind_api.services.planning.payloads import build_trip_request_payload


class TripRefinementOperations(Protocol):
    def check_cancelled(self) -> None:
        ...

    def assess_refinement(self, state: TripRefinementState) -> dict[str, Any]:
        ...

    def refine_itinerary(self, state: TripRefinementState) -> dict[str, Any]:
        ...

    def validate_refinement(self, state: TripRefinementState) -> dict[str, Any]:
        ...

    def repair_refinement(self, state: TripRefinementState) -> dict[str, Any]:
        ...

    def assemble_refinement(self, state: TripRefinementState) -> dict[str, Any]:
        ...


def build_refinement_fingerprint(
    *,
    trip_request: dict[str, Any],
    current_plan: dict[str, Any],
    refinement_context: dict[str, Any],
    instruction: str,
    scope: str,
    day_index: int | None,
    prompt_version: str,
    endpoint: LlmEndpointConfig,
) -> str:
    canonical = json.dumps(
        {
            "graph_version": TRIP_REFINEMENT_GRAPH_VERSION,
            "schema_version": TRIP_REFINEMENT_STATE_SCHEMA_VERSION,
            "trip_request": trip_request,
            "current_plan": current_plan,
            "refinement_context": refinement_context,
            "instruction": instruction,
            "scope": scope,
            "day_index": day_index,
            "prompt_version": prompt_version,
            "model_identity": non_sensitive_model_identity(endpoint),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_refinement_initial_state(
    request: PlanningRequest,
    current_plan: PlanningResult,
    *,
    context: RefinementContext,
    instruction: str,
    scope: str,
    day_index: int | None,
    run_id: str,
    prompt_version: str,
    endpoint: LlmEndpointConfig,
) -> TripRefinementState:
    trip_request = build_trip_request_payload(request)
    current_payload = current_plan.model_dump(mode="json")
    context_payload = context.model_dump(mode="json")
    return {
        "run_id": run_id,
        "graph_version": TRIP_REFINEMENT_GRAPH_VERSION,
        "schema_version": TRIP_REFINEMENT_STATE_SCHEMA_VERSION,
        "input_fingerprint": build_refinement_fingerprint(
            trip_request=trip_request,
            current_plan=current_payload,
            refinement_context=context_payload,
            instruction=instruction,
            scope=scope,
            day_index=day_index,
            prompt_version=prompt_version,
            endpoint=endpoint,
        ),
        "trip_request": trip_request,
        "current_plan": current_payload,
        "refinement_context": context_payload,
        "instruction": instruction,
        "scope": scope,
        "day_index": day_index,
        "role_results": {},
        "repair_count": 0,
        "validation_errors": [],
    }


def build_trip_refinement_graph(
    operations: TripRefinementOperations,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
):
    def guarded(operation):
        def run(state: TripRefinementState) -> dict[str, Any]:
            operations.check_cancelled()
            result = operation(state)
            operations.check_cancelled()
            return result

        return run

    builder = StateGraph(TripRefinementState)
    builder.add_node("scope_assessment", guarded(operations.assess_refinement))
    builder.add_node("itinerary_refiner", guarded(operations.refine_itinerary))
    builder.add_node("refinement_validation", guarded(operations.validate_refinement))
    builder.add_node("refinement_repair", guarded(operations.repair_refinement))
    builder.add_node("refinement_assembly", guarded(operations.assemble_refinement))
    builder.add_edge(START, "scope_assessment")
    builder.add_edge("scope_assessment", "itinerary_refiner")
    builder.add_edge("itinerary_refiner", "refinement_validation")

    def route_after_validation(state: TripRefinementState) -> str:
        if not state.get("validation_errors"):
            return "refinement_assembly"
        if int(state.get("repair_count", 0)) >= 1:
            raise ValueError("Refined itinerary still failed validation after one repair")
        return "refinement_repair"

    builder.add_conditional_edges(
        "refinement_validation",
        route_after_validation,
        {
            "refinement_repair": "refinement_repair",
            "refinement_assembly": "refinement_assembly",
        },
    )
    builder.add_edge("refinement_repair", "refinement_validation")
    builder.add_edge("refinement_assembly", END)
    return builder.compile(checkpointer=checkpointer)
