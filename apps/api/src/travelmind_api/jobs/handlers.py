from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status

from travelmind_api.agents.base import PlanningRequest, PlanningResult
from travelmind_api.agents.factory import build_orchestrator
from travelmind_api.core.config import get_settings
from travelmind_api.core.database import session_scope
from travelmind_api.db.models import JobRecord, Trip
from travelmind_api.services.export_service import write_pdf_export
from travelmind_api.services.job_service import ensure_job_record_schema, update_job_state


settings = get_settings()


@dataclass(frozen=True)
class JobExecution:
    id: str
    type: str
    trip_id: str | None
    payload: dict


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _extract_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            message = detail.get("message") or detail.get("detail") or detail.get("code")
            if message:
                return str(message)
            return str(detail)
        if detail:
            return str(detail)
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _transition_job(job_id: str, *, stage: str, stage_message: str, progress_percent: int) -> None:
    with session_scope() as session:
        update_job_state(
            session,
            job_id,
            status="running",
            stage=stage,
            stage_message=stage_message,
            progress_percent=progress_percent,
            error_message=None,
            result=None,
            set_started=True,
            clear_finished=True,
        )


def _mark_complete(job_id: str, result: dict, *, stage: str, stage_message: str) -> None:
    with session_scope() as session:
        update_job_state(
            session,
            job_id,
            status="completed",
            stage=stage,
            stage_message=stage_message,
            progress_percent=100,
            result=result,
            error_message=None,
            set_started=True,
            set_finished=True,
        )


def _mark_failed(job_id: str, message: str) -> None:
    with session_scope() as session:
        update_job_state(
            session,
            job_id,
            status="failed",
            stage_message=message,
            error_message=message,
            set_finished=True,
        )


def _claim_job(job_id: str) -> JobExecution | None:
    now = _utcnow()
    with session_scope() as session:
        ensure_job_record_schema(session)
        claimed = (
            session.query(JobRecord)
            .filter(JobRecord.id == job_id, JobRecord.status == "queued")
            .update(
                {
                    JobRecord.status: "running",
                    JobRecord.started_at: now,
                    JobRecord.finished_at: None,
                    JobRecord.result_json: None,
                    JobRecord.error_message: None,
                    JobRecord.updated_at: now,
                },
                synchronize_session=False,
            )
        )
        if claimed == 0:
            return None
        job = session.query(JobRecord).filter(JobRecord.id == job_id).one()
        return JobExecution(id=job.id, type=job.type, trip_id=job.trip_id, payload=job.payload_json or {})


def _build_request(trip: Trip) -> PlanningRequest:
    return PlanningRequest(
        trip_id=trip.id,
        title=trip.title,
        destination=trip.destination,
        start_date=trip.start_date,
        end_date=trip.end_date,
        budget=trip.budget,
        travelers=trip.travelers,
        interests=trip.interests or [],
        accommodation_preference=trip.accommodation_preference,
        pace=trip.pace,
        transport_mode=trip.transport_mode,
    )


def _load_plan_from_trip(trip: Trip) -> PlanningResult | None:
    if not trip.itinerary_json:
        return None
    return PlanningResult(
        **trip.itinerary_json,
        trace=trip.latest_agent_trace_json or {"provider": "unknown", "workflow_id": "n/a", "notes": []},
    )


def _require_day(plan: PlanningResult, day_index: int) -> None:
    if not any(day.day_index == day_index for day in plan.days):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_refine_day", "message": f"day_index {day_index} is outside the itinerary range"},
        )


def _apply_refinement(plan: PlanningResult, *, instruction: str, scope: str, day_index: int | None) -> PlanningResult:
    refined = plan.model_copy(deep=True)
    refined.trace.notes.append("Applied MVP refine flow through the existing job pipeline.")
    refined.trace.notes.append(f"Refine scope: {scope}.")
    if day_index is not None:
        _require_day(refined, day_index)
        refined.trace.notes.append(f"Refined day {day_index}.")
    refined.trace.notes.append(f"Instruction: {instruction}")

    if day_index is not None:
        for day in refined.days:
            if day.day_index != day_index:
                continue
            day.title = f"{day.title} | Refined"
            day.summary = f"{day.summary} Refinement: {instruction}."
            if day.items:
                day.items[0].note = f"{day.items[0].note} Refinement: {instruction}."
            break
        refined.summary = f"{refined.summary} Refined day {day_index} for {scope}."
    else:
        refined.summary = f"{refined.summary} Refined for {scope}: {instruction}."
        if refined.days:
            refined.days[0].summary = f"{refined.days[0].summary} Refinement scope {scope}: {instruction}."
            if refined.days[0].items:
                refined.days[0].items[0].note = f"{refined.days[0].items[0].note} Refinement scope {scope}: {instruction}."

    return refined


def _persist_trip_plan(trip: Trip, plan: PlanningResult) -> dict:
    trip.itinerary_json = plan.model_dump(mode="json", exclude={"trace"})
    trip.latest_agent_trace_json = plan.trace.model_dump(mode="json")
    return trip.latest_agent_trace_json


def _process_trip_generation(job: JobExecution) -> dict:
    _transition_job(job.id, stage="brief_parsing", stage_message="Parsing trip brief.", progress_percent=10)
    with session_scope() as session:
        trip = session.query(Trip).filter(Trip.id == job.trip_id).one_or_none()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found for job")
        request = _build_request(trip)
        orchestrator = build_orchestrator(settings)

        _transition_job(job.id, stage="source_search", stage_message="Collecting grounded source inputs.", progress_percent=25)
        _transition_job(job.id, stage="source_scoring", stage_message="Scoring grounded source inputs.", progress_percent=45)
        _transition_job(job.id, stage="route_planning", stage_message="Drafting the itinerary route.", progress_percent=72)
        result = orchestrator.plan_trip(request)
        _transition_job(job.id, stage="hotel_matching", stage_message="Filling accommodation placeholders.", progress_percent=88)
        _transition_job(job.id, stage="export_ready", stage_message="Finalizing itinerary payload.", progress_percent=96)

        agent_trace = _persist_trip_plan(trip, result)
        session.add(trip)
        session.flush()
        return {
            "trip_id": trip.id,
            "summary": result.summary,
            "agent_trace": agent_trace,
        }


def _process_trip_refine(job: JobExecution) -> dict:
    instruction = str(job.payload.get("instruction", "")).strip()
    scope = str(job.payload.get("scope", "trip")).strip() or "trip"
    day_index_raw = job.payload.get("day_index")
    day_index = int(day_index_raw) if day_index_raw is not None else None

    if not instruction:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_refine_instruction", "message": "instruction cannot be empty"},
        )

    _transition_job(job.id, stage="brief_parsing", stage_message="Parsing refine instruction.", progress_percent=8)
    with session_scope() as session:
        trip = session.query(Trip).filter(Trip.id == job.trip_id).one_or_none()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found for job")
        request = _build_request(trip)
        orchestrator = build_orchestrator(settings)

        _transition_job(job.id, stage="source_search", stage_message="Collecting context for refinement.", progress_percent=24)
        _transition_job(job.id, stage="source_scoring", stage_message="Scoring refinement context.", progress_percent=42)
        base_plan = _load_plan_from_trip(trip)
        if base_plan is None:
            _transition_job(job.id, stage="route_planning", stage_message="Generating a base itinerary before refinement.", progress_percent=64)
            base_plan = orchestrator.plan_trip(request)
        else:
            _transition_job(job.id, stage="route_planning", stage_message="Reworking the selected itinerary scope.", progress_percent=64)
        refined_plan = _apply_refinement(base_plan, instruction=instruction, scope=scope, day_index=day_index)
        _transition_job(job.id, stage="hotel_matching", stage_message="Rebalancing stay placeholders after refinement.", progress_percent=86)
        _transition_job(job.id, stage="export_ready", stage_message="Finalizing refined itinerary payload.", progress_percent=96)

        agent_trace = _persist_trip_plan(trip, refined_plan)
        session.add(trip)
        session.flush()
        return {
            "trip_id": trip.id,
            "summary": refined_plan.summary,
            "instruction": instruction,
            "scope": scope,
            "day_index": day_index,
            "agent_trace": agent_trace,
        }


def _process_pdf_export(job: JobExecution) -> dict:
    _transition_job(job.id, stage="brief_parsing", stage_message="Preparing itinerary export input.", progress_percent=18)
    with session_scope() as session:
        trip = session.query(Trip).filter(Trip.id == job.trip_id).one_or_none()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found for job")
        if not trip.itinerary_json:
            raise HTTPException(status_code=400, detail="Generate itinerary before export")
        orchestrator = build_orchestrator(settings)
        request = _build_request(trip)
        plan = _load_plan_from_trip(trip)
        if plan is None:
            raise HTTPException(status_code=400, detail="Generate itinerary before export")
        _transition_job(job.id, stage="export_ready", stage_message="Rendering PDF export payload.", progress_percent=82)
        draft = orchestrator.draft_export_payload(request, plan)
        export_result = write_pdf_export(job.id, draft, settings)
        return export_result


def process_job(job_id: str) -> None:
    job = _claim_job(job_id)
    if not job:
        return

    try:
        if job.type == "trip.generate":
            result = _process_trip_generation(job)
            completion_message = "Itinerary ready for review and export."
        elif job.type == "trip.refine":
            result = _process_trip_refine(job)
            completion_message = "Refined itinerary ready for review and export."
        elif job.type == "export.pdf":
            result = _process_pdf_export(job)
            completion_message = "PDF export ready."
        else:
            raise RuntimeError(f"Unsupported job type: {job.type}")
        _mark_complete(job.id, result, stage="export_ready", stage_message=completion_message)
    except Exception as exc:  # pragma: no cover
        _mark_failed(job.id, _extract_error_message(exc))

