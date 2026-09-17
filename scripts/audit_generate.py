from __future__ import annotations

import json
import argparse
from datetime import date, datetime
from pathlib import Path

from travelmind_api.agents.helloagents import HelloAgentsOrchestrator
from travelmind_api.core.database import SessionLocal
from travelmind_api.db.models import JobRecord, Trip
from travelmind_api.services.job_service import create_job
from travelmind_api.jobs.handlers import process_job
from travelmind_api.core.security import generate_identifier
from travelmind_api.jobs import handlers as handlers_module


USER_ID = "usr_ae160ee04edf63650dba"


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and capture a TravelMind itinerary audit.")
    parser.add_argument("--destination", default="", help="Override the source trip destination, for example 上海")
    parser.add_argument("--origin", default="", help="Override the source trip origin")
    parser.add_argument("--title", default="", help="Override the generated audit trip title")
    parser.add_argument("--start-date", default="", help="Override start date in YYYY-MM-DD format")
    parser.add_argument("--end-date", default="", help="Override end date in YYYY-MM-DD format")
    parser.add_argument(
        "--interests",
        default="",
        help="Comma-separated interest list used instead of the source trip interests",
    )
    parser.add_argument(
        "--main-wire-api",
        choices=("responses", "chat_completions"),
        default="",
        help="Temporarily override only the primary planner/brief wire API for this audit run",
    )
    args = parser.parse_args()
    audit_interests = [item.strip() for item in args.interests.replace("，", ",").split(",") if item.strip()]

    if args.main_wire_api:
        original_resolve_llm_config = handlers_module._resolve_llm_config

        def audit_resolve_llm_config(user, payload):
            config = original_resolve_llm_config(user, payload)
            if config is None:
                return None
            return config.model_copy(update={"wire_api": args.main_wire_api})

        handlers_module._resolve_llm_config = audit_resolve_llm_config

    captured: list[dict] = []
    original_run_role = HelloAgentsOrchestrator._run_role

    def audited_run_role(self, *, module, role_config, llm_config, input_payload):
        enriched_payload = self._augment_payload_with_tool_results(role_config.role_name, input_payload)
        prompt_payload = self._build_role_prompt_payload(enriched_payload, role_name=role_config.role_name)
        record = {
            "role": role_config.role_name,
            "title": role_config.title,
            "model": llm_config.model,
            "wire_api": llm_config.wire_api,
            "provider_protocol": llm_config.provider_protocol,
            "system_prompt": role_config.system_prompt,
            "input_payload": prompt_payload,
        }
        try:
            result = original_run_role(
                self,
                module=module,
                role_config=role_config,
                llm_config=llm_config,
                input_payload=input_payload,
            )
        except Exception as exc:
            record["error"] = f"{exc.__class__.__name__}: {exc}"
            captured.append(record)
            raise
        record["raw_return"] = result
        try:
            # Mirror the orchestrator's tolerant JSON extraction so audits do
            # not report a false parse failure when a model appends a revised
            # object after its first complete JSON response.
            record["parsed_return"] = self._extract_json_payload(result)
        except (TypeError, ValueError, json.JSONDecodeError):
            record["parsed_return"] = None
        captured.append(record)
        return result

    HelloAgentsOrchestrator._run_role = audited_run_role
    session = SessionLocal()
    try:
        source = (
            session.query(Trip)
            .filter(Trip.user_id == USER_ID)
            .order_by(Trip.created_at.desc())
            .first()
        )
        if source is None:
            raise RuntimeError(f"No source trip found for user {USER_ID}")
        trip = Trip(
            id=generate_identifier("trip"),
            user_id=source.user_id,
            title=args.title or f"审计-{args.destination or source.destination}-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
            origin=args.origin or source.origin,
            destination=args.destination or source.destination,
            start_date=date.fromisoformat(args.start_date) if args.start_date else source.start_date,
            end_date=date.fromisoformat(args.end_date) if args.end_date else source.end_date,
            budget=source.budget,
            travelers=source.travelers,
            interests=audit_interests or list(source.interests or []),
            accommodation_preference=source.accommodation_preference,
            pace=source.pace,
            transport_mode=source.transport_mode,
        )
        session.add(trip)
        job = create_job(
            session,
            job_type="trip.generate",
            owner_user_id=trip.user_id,
            trip_id=trip.id,
            payload={"trip_id": trip.id, "audit_generation": True},
        )
        session.commit()
        trip_id = trip.id
        job_id = job.id
    finally:
        session.close()

    process_job(job_id)

    session = SessionLocal()
    try:
        job = session.get(JobRecord, job_id)
        trip = session.get(Trip, trip_id)
        output_dir = Path(".tmp/agent-audit")
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{job_id}.json"
        audit = {
            "created_at": datetime.now().astimezone().isoformat(),
            "trip_id": trip_id,
            "job_id": job_id,
            "job_status": job.status if job else None,
            "trip_title": trip.title if trip else None,
            "records": captured,
            "final_itinerary": trip.itinerary_json if trip else None,
            "final_agent_trace": trip.latest_agent_trace_json if trip else None,
            "job_result": job.result_json if job else None,
            "job_error": job.error_message if job else None,
        }
        output_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"audit_path": str(output_path), "trip_id": trip_id, "job_id": job_id, "status": audit["job_status"], "stages": [item["role"] for item in captured]}, ensure_ascii=False))
    finally:
        session.close()


if __name__ == "__main__":
    main()
