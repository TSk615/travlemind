from __future__ import annotations

import argparse
import json
from pathlib import Path

from travelmind_api.agents.base import AgentTrace, PlanningResult
from travelmind_api.agents.planning_core import PlanningCore, PoiGrounding
from travelmind_api.core.database import SessionLocal
from travelmind_api.db.models import Trip, User
from travelmind_api.jobs.handlers import _build_request, _persist_trip_plan
from travelmind_api.services.budgeting import enrich_plan_with_budget
from travelmind_api.services.weather_evidence import has_unsupported_weather_condition


def main() -> None:
    parser = argparse.ArgumentParser(description="Recalculate one stored trip using the deterministic budget ledger.")
    parser.add_argument("trip_id")
    parser.add_argument("--audit", default="", help="Optional audit JSON used to restore researched nearby POIs.")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        trip = session.get(Trip, args.trip_id)
        if trip is None or not trip.itinerary_json:
            raise RuntimeError("Trip or itinerary not found")
        user = session.get(User, trip.user_id)
        request = _build_request(trip, user)
        trace = AgentTrace.model_validate(trip.latest_agent_trace_json or {
            "provider": "maintenance",
            "workflow_id": "budget-recalculation",
            "notes": [],
        })
        plan = PlanningResult.model_validate({**trip.itinerary_json, "trace": trace})
        if args.audit:
            audit = json.loads(Path(args.audit).read_text(encoding="utf-8"))
            poi_record = next(
                (row for row in audit.get("records", []) if row.get("role") == "poi_specialist"),
                None,
            )
            if not poi_record or not poi_record.get("parsed_return"):
                raise RuntimeError("Audit does not contain a parsed POI specialist result")
            grounding = PoiGrounding.model_validate(poi_record["parsed_return"])
            for day in plan.days:
                for item in day.items:
                    item.nearby_suggestions = []
            PlanningCore(None)._attach_nearby_poi_suggestions(plan.days, grounding)
        verified_conditions = [
            day.weather.condition
            for day in plan.days
            if day.weather and day.weather.forecast_type == "short_range" and day.weather.citations
        ]
        plan.risks = [
            risk for risk in plan.risks
            if not has_unsupported_weather_condition(risk, verified_conditions)
        ]
        plan = enrich_plan_with_budget(plan, request)
        _persist_trip_plan(trip, plan)
        session.add(trip)
        session.commit()
        print(json.dumps({
            "trip_id": trip.id,
            "estimated_total": plan.total_budget_estimate,
            "breakdown": plan.budget_summary.breakdown.model_dump(mode="json") if plan.budget_summary else None,
        }, ensure_ascii=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
