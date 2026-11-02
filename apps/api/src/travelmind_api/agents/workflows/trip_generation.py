from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from travelmind_api.agents.base import PlanningRequest
from travelmind_api.agents.runtime import WorkflowRuntime
from travelmind_api.agents.workflows.state import (
    TRIP_GENERATION_GRAPH_VERSION,
    TRIP_GENERATION_STATE_SCHEMA_VERSION,
    TripGenerationState,
    build_input_fingerprint,
    non_sensitive_model_identity,
)
from travelmind_api.prompts.roles.trip import build_brief_parser_prompt
from travelmind_api.services.llm.config import LlmEndpointConfig
from travelmind_api.services.llm.localization import build_output_language_instruction, infer_output_locale
from travelmind_api.services.llm.role_invoker import RoleInvocation, RoleInvoker
from travelmind_api.services.planning.payloads import build_trip_request_payload
from travelmind_api.services.planning.role_models import PlanningBrief, parse_structured_response


@dataclass(frozen=True)
class TripGenerationDependencies:
    role_invoker: RoleInvoker
    brief_endpoint: LlmEndpointConfig
    runtime: WorkflowRuntime


class TripGenerationOperations(Protocol):
    """Business operations plugged into the framework-owned graph topology."""

    def parse_brief(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def research_pois(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def research_weather(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def join_initial_research(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def research_hotels(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def research_transport(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def verify_evidence(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def draft_itinerary(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def validate_itinerary(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def repair_itinerary(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def assemble_result(self, state: TripGenerationState) -> dict[str, Any]:
        ...

    def check_cancelled(self) -> None:
        ...


def build_initial_state(
    request: PlanningRequest,
    *,
    run_id: str,
    brief_endpoint: LlmEndpointConfig,
) -> TripGenerationState:
    prompt = build_brief_parser_prompt()
    trip_payload = build_trip_request_payload(request)
    output_locale = infer_output_locale(request)
    return {
        "run_id": run_id,
        "graph_version": TRIP_GENERATION_GRAPH_VERSION,
        "schema_version": TRIP_GENERATION_STATE_SCHEMA_VERSION,
        "input_fingerprint": build_input_fingerprint(
            trip_request=trip_payload,
            output_locale=output_locale,
            prompt_versions={"brief_parser": prompt.version},
            model_identities={"brief_parser": non_sensitive_model_identity(brief_endpoint)},
        ),
        "output_locale": output_locale,
        "trip_request": trip_payload,
        "role_results": {},
    }


def build_brief_probe_graph(
    dependencies: TripGenerationDependencies,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
):
    def parse_brief(state: TripGenerationState) -> dict[str, Any]:
        dependencies.runtime.emit_progress(
            "brief_parser",
            "Brief parser",
            "Compresses the trip input into a compact planning brief.",
            24,
        )
        prompt = build_brief_parser_prompt()
        output_locale = state.get("output_locale", "zh-CN")
        result = dependencies.role_invoker.invoke(
            RoleInvocation(
                role_name="brief_parser",
                prompt_version=prompt.version,
                system_prompt=(
                    f"{prompt.system_prompt} "
                    f"{build_output_language_instruction(output_locale)}"
                    f" Target output locale: {output_locale}."
                ),
                input_payload={"trip_request": state["trip_request"]},
                endpoint=dependencies.brief_endpoint,
            )
        )
        dependencies.runtime.check_cancelled()
        brief = parse_structured_response(result.content, PlanningBrief)
        role_results = dict(state.get("role_results", {}))
        role_results["brief_parser"] = result.checkpoint_metadata()
        return {
            "planning_brief": brief.model_dump(mode="json"),
            "role_results": role_results,
        }

    builder = StateGraph(TripGenerationState)
    builder.add_node("brief_parser", parse_brief)
    builder.add_edge(START, "brief_parser")
    builder.add_edge("brief_parser", END)
    return builder.compile(checkpointer=checkpointer)


def run_brief_probe(
    request: PlanningRequest,
    *,
    dependencies: TripGenerationDependencies,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> TripGenerationState:
    graph = build_brief_probe_graph(dependencies, checkpointer=checkpointer)
    initial_state = build_initial_state(
        request,
        run_id=dependencies.runtime.run_id,
        brief_endpoint=dependencies.brief_endpoint,
    )
    config = {"configurable": {"thread_id": dependencies.runtime.run_id}}
    return graph.invoke(initial_state, config=config)


def build_trip_generation_graph(
    operations: TripGenerationOperations,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
):
    """Build the six-role generation graph with explicit batch joins.

    The list-form edges are intentional: POI/weather and hotel/transport must
    both finish before their downstream join runs.
    """

    def guarded(operation):
        def run(state: TripGenerationState) -> dict[str, Any]:
            operations.check_cancelled()
            result = operation(state)
            operations.check_cancelled()
            return result

        return run

    builder = StateGraph(TripGenerationState)
    builder.add_node("brief_parser", guarded(operations.parse_brief))
    builder.add_node("poi_specialist", guarded(operations.research_pois))
    builder.add_node("weather_specialist", guarded(operations.research_weather))
    builder.add_node("initial_research_join", guarded(operations.join_initial_research))
    builder.add_node("hotel_specialist", guarded(operations.research_hotels))
    builder.add_node("transport_specialist", guarded(operations.research_transport))
    builder.add_node("evidence_join", guarded(operations.verify_evidence))
    builder.add_node("itinerary_planner", guarded(operations.draft_itinerary))
    builder.add_node("execution_validation", guarded(operations.validate_itinerary))
    builder.add_node("itinerary_repair", guarded(operations.repair_itinerary))
    builder.add_node("result_assembly", guarded(operations.assemble_result))

    builder.add_edge(START, "brief_parser")
    builder.add_edge("brief_parser", "poi_specialist")
    builder.add_edge("brief_parser", "weather_specialist")
    builder.add_edge(["poi_specialist", "weather_specialist"], "initial_research_join")
    builder.add_edge("initial_research_join", "hotel_specialist")
    builder.add_edge("initial_research_join", "transport_specialist")
    builder.add_edge(["hotel_specialist", "transport_specialist"], "evidence_join")
    builder.add_edge("evidence_join", "itinerary_planner")
    builder.add_edge("itinerary_planner", "execution_validation")

    def route_after_validation(state: TripGenerationState) -> str:
        from travelmind_api.services.planner_reliability import can_repair
        # Never risk a valid draft merely to rewrite soft/unknown observations.
        if not state.get("validation_errors"):
            return "result_assembly"
        if not can_repair(state):
            raise ValueError("Planner repair budget exhausted before validated result")
        return "itinerary_repair"

    builder.add_conditional_edges(
        "execution_validation",
        route_after_validation,
        {
            "itinerary_repair": "itinerary_repair",
            "result_assembly": "result_assembly",
        },
    )
    builder.add_edge("itinerary_repair", "execution_validation")
    builder.add_edge("result_assembly", END)
    return builder.compile(checkpointer=checkpointer)
