"""Recover a planner-complete audit that was rejected by a now-fixed local validator."""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from travelmind_api.agents.base import AgentRunStep
from travelmind_api.agents.helloagents import (
    HelloAgentsHotelRecommendation,
    HelloAgentsOrchestrator,
    HelloAgentsPoiGrounding,
    HelloAgentsTransportGuidance,
    HelloAgentsWeatherGuidance,
)
from travelmind_api.core.database import SessionLocal
from travelmind_api.db.models import Trip, User
from travelmind_api.jobs.handlers import _build_request, _persist_trip_plan, _resolve_llm_config
from travelmind_api.services.llm.parser import LlmPlanningPayload
from travelmind_api.services.trip_image_enrichment import enrich_plan_images, prepare_plan_images_for_async_enrichment


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audit")
    args = parser.parse_args()
    audit_path = Path(args.audit)
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    records = {row["role"]: row for row in audit["records"]}
    required = {"poi_specialist", "weather_specialist", "hotel_specialist", "transport_specialist", "itinerary_planner"}
    missing = sorted(role for role in required if not records.get(role, {}).get("parsed_return"))
    if missing:
        raise RuntimeError(f"审计记录缺少可恢复阶段：{', '.join(missing)}")

    session = SessionLocal()
    try:
        trip = session.get(Trip, audit["trip_id"])
        if trip is None:
            raise RuntimeError("审计行程不存在")
        user = session.get(User, trip.user_id)
        request = _build_request(trip, user)
        llm_config = _resolve_llm_config(user, {})
        if llm_config is None:
            raise RuntimeError("用户未配置主模型")
        orchestrator = HelloAgentsOrchestrator(llm_config)

        payload = LlmPlanningPayload.model_validate(records["itinerary_planner"]["parsed_return"])
        poi = HelloAgentsPoiGrounding.model_validate(records["poi_specialist"]["parsed_return"])
        weather = HelloAgentsWeatherGuidance.model_validate(records["weather_specialist"]["parsed_return"])
        planner_input = records["itinerary_planner"].get("input_payload") or {}
        hotel = HelloAgentsHotelRecommendation.model_validate(
            planner_input.get("hotels") or records["hotel_specialist"]["parsed_return"]
        )
        transport = HelloAgentsTransportGuidance.model_validate(records["transport_specialist"]["parsed_return"])
        orchestrator._validate_execution_constraints(payload, request, transport)

        documents = []
        for item in poi.top_pois:
            for url in [item.source_url, *item.source_urls]:
                if url and not any(row["url"] == url for row in documents):
                    documents.append({"title": item.name or item.name_cn or item.name_en, "url": url})
        weather_urls = list(dict.fromkeys([
            *weather.source_urls,
            *(url for forecast in weather.daily_forecasts for url in forecast.source_urls),
        ]))
        agent_runs = [
            AgentRunStep(
                key=role,
                title=str(records[role].get("title") or role),
                description="从完整审计记录恢复；未重新调用该角色。",
                prompt_version="audit-recovery.v1",
                model=records[role].get("model"),
                notes=["原始提示词与返回保留在来源审计文件中。"],
            )
            for role in ("brief_parser", "poi_specialist", "weather_specialist", "hotel_specialist", "transport_specialist", "itinerary_planner")
            if role in records
        ]
        plan = orchestrator._build_result_from_payload(
            payload,
            request,
            ["由完整模型返回恢复；原失败由已修复的 local_transport 返程取点误判造成。"],
            agent_runs,
            poi_grounding=poi,
            weather_guidance=weather,
            weather_citations=weather_urls,
            grounding_documents=documents,
            hotel_recommendation=hotel,
            transport_guidance=transport,
        )
        plan = prepare_plan_images_for_async_enrichment(plan)
        plan = enrich_plan_images(
            plan,
            request,
            search_service=request.search_service,
            force=True,
            review_config=llm_config,
        )
        _persist_trip_plan(trip, plan)
        session.add(trip)
        session.commit()

        output_path = audit_path.with_name(f"{audit_path.stem}-recovered-{datetime.now():%Y%m%d-%H%M%S}.json")
        output_path.write_text(json.dumps({
            "created_at": datetime.now().astimezone().isoformat(),
            "source_audit": str(audit_path),
            "trip_id": trip.id,
            "final_itinerary": trip.itinerary_json,
            "final_agent_trace": trip.latest_agent_trace_json,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        image_rows = [
            {"name": item.name, "status": item.image_status, "images": item.image_urls,
             "sources": item.image_source_urls, "failure": item.image_failure_reason}
            for day in plan.days for item in day.items if item.type == "sight"
        ]
        print(json.dumps({"audit_path": str(output_path), "trip_id": trip.id, "images": image_rows}, ensure_ascii=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
