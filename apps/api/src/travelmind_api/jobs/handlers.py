from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from fastapi import HTTPException, status

from travelmind_api.agents.base import PlanningRequest, PlanningResult
from travelmind_api.agents.factory import build_orchestrator
from travelmind_api.agents.provider import normalize_agent_provider
from travelmind_api.core.config import get_settings
from travelmind_api.core.database import session_scope
from travelmind_api.core.logging_utils import job_log_path, log_job_event, reset_current_job_id, set_current_job_id
from travelmind_api.core.upstream_urls import normalize_upstream_base_url
from travelmind_api.db.models import ImageGeneration, JobRecord, Trip, User
from travelmind_api.services.image_prompt_service import ImagePromptComposePayload, compose_image_prompt
from travelmind_api.services.image_storage import persist_bytes
from travelmind_api.services.images import ImageModelConfig, ImageProviderRequest, build_image_provider
from travelmind_api.services.export_service import normalize_export_formats, write_export_bundle
from travelmind_api.services.job_service import create_job, dispatch_job_now, update_job_state
from travelmind_api.services.llm import LlmConfig
from travelmind_api.services.llm.user_config import build_user_poi_role_overrides, user_poi_role_override_missing_fields
from travelmind_api.services.search_connector import resolve_search_service_config
from travelmind_api.services.trip_image_enrichment import enrich_plan_images, prepare_plan_images_for_async_enrichment
from travelmind_api.services.trip_service import validate_trip_dates_for_generation


settings = get_settings()
_LOGGER = logging.getLogger(__name__)


class JobCancelledError(RuntimeError):
    pass


class JobRetryRequested(RuntimeError):
    def __init__(self, delay_seconds: int):
        super().__init__(f"Retry job after {delay_seconds} seconds")
        self.delay_seconds = delay_seconds


@dataclass(frozen=True)
class JobExecution:
    id: str
    type: str
    trip_id: str | None
    payload: dict
    attempt_count: int
    max_attempts: int



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


def _is_retryable_error(exc: Exception) -> bool:
    if isinstance(exc, HTTPException):
        return exc.status_code == 429 or exc.status_code >= 500
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    message = _extract_error_message(exc).lower()
    return any(
        marker in message
        for marker in (
            "429",
            "rate limit",
            "too many requests",
            "timeout",
            "timed out",
            "temporarily unavailable",
            "connection reset",
            "connection refused",
            "bad gateway",
            "service unavailable",
        )
    )


def _schedule_retry(job_id: str, exc: Exception) -> int | None:
    if not _is_retryable_error(exc):
        return None
    with session_scope() as session:
        job = session.query(JobRecord).filter(JobRecord.id == job_id).one_or_none()
        if job is None or job.status in {"cancelled", "completed"} or job.attempt_count >= job.max_attempts:
            return None
        delay_seconds = min(
            max(settings.job_retry_base_seconds, 1) * (2 ** max(job.attempt_count - 1, 0)),
            300,
        )
        message = _extract_error_message(exc)
        updated = update_job_state(
            session,
            job_id,
            status="retrying",
            stage="retry_wait",
            stage_message=f"Transient failure; retrying in {delay_seconds} seconds: {message}",
            error_message=message,
            clear_finished=True,
        )
        if updated is not None:
            updated.locked_at = None
            updated.heartbeat_at = None
            updated.available_at = _utcnow()
            session.add(updated)
        return delay_seconds


def _job_status(job_id: str) -> str | None:
    with session_scope() as session:
        job = session.query(JobRecord).filter(JobRecord.id == job_id).one_or_none()
        return str(job.status) if job is not None else None


def _raise_if_cancelled(job_id: str) -> None:
    if _job_status(job_id) == "cancelled":
        raise JobCancelledError(f"Job {job_id} was cancelled.")



def _transition_job(job_id: str, *, stage: str, stage_message: str, progress_percent: int) -> None:
    _raise_if_cancelled(job_id)
    log_job_event(
        "job_transition",
        job_id=job_id,
        logger_name=__name__,
        message=stage_message,
        stage=stage,
        progress_percent=progress_percent,
    )
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
            skip_if_terminal=True,
        )



def _mark_complete(job_id: str, result: dict, *, stage: str, stage_message: str) -> None:
    log_job_event(
        "job_completed",
        job_id=job_id,
        logger_name=__name__,
        message=stage_message,
        stage=stage,
        progress_percent=100,
        result_keys=sorted(result.keys()) if isinstance(result, dict) else [],
    )
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
            skip_if_terminal=True,
        )



def _mark_failed(job_id: str, message: str) -> None:
    log_path = job_log_path(job_id)
    failure_message = f"{message} (log: {log_path.as_posix()})"
    log_job_event(
        "job_failed",
        job_id=job_id,
        logger_name=__name__,
        level="ERROR",
        message=message,
        log_path=log_path.as_posix(),
    )
    with session_scope() as session:
        update_job_state(
            session,
            job_id,
            status="failed",
            stage_message=failure_message,
            error_message=failure_message,
            set_finished=True,
            skip_if_terminal=True,
        )


def _record_trip_generation_resume_checkpoint(job_id: str, checkpoint: dict[str, Any] | None, exc: Exception) -> None:
    if not isinstance(checkpoint, dict):
        return
    checkpoint_payload = deepcopy(checkpoint)
    checkpoint_payload["source_job_id"] = job_id
    checkpoint_payload.setdefault("failure_message", _extract_error_message(exc))
    roles = checkpoint_payload.get("roles") if isinstance(checkpoint_payload.get("roles"), dict) else {}
    completed_roles = [
        role_name
        for role_name, role_payload in roles.items()
        if isinstance(role_payload, dict) and role_payload.get("status") == "completed"
    ]
    checkpoint_payload["completed_roles"] = completed_roles
    failed_role = str(checkpoint_payload.get("failed_role") or "").strip() or None
    with session_scope() as session:
        job = session.query(JobRecord).filter(JobRecord.id == job_id).one_or_none()
        if job is None:
            return
        payload = dict(job.payload_json or {})
        payload["resume_checkpoint"] = checkpoint_payload
        job.payload_json = payload
        job.result_json = {
            "resume_available": True,
            "resume_failed_role": failed_role,
            "resume_completed_roles": completed_roles,
            "resume_reason": checkpoint_payload.get("failure_message"),
        }
        session.add(job)



def _claim_job(job_id: str) -> JobExecution | None:
    now = _utcnow()
    with session_scope() as session:
        claimed = (
            session.query(JobRecord)
            .filter(JobRecord.id == job_id, JobRecord.status.in_(("queued", "retrying")))
            .update(
                {
                    JobRecord.status: "running",
                    JobRecord.started_at: now,
                    JobRecord.attempt_count: JobRecord.attempt_count + 1,
                    JobRecord.locked_at: now,
                    JobRecord.heartbeat_at: now,
                    JobRecord.available_at: None,
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
        return JobExecution(
            id=job.id,
            type=job.type,
            trip_id=job.trip_id,
            payload=job.payload_json or {},
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
        )



def _build_request(trip: Trip, user: User | None = None) -> PlanningRequest:
    planning_generated_at = datetime.now().astimezone()
    return PlanningRequest(
        trip_id=trip.id,
        user_id=getattr(user, "id", None),
        title=trip.title,
        origin=trip.origin,
        destination=trip.destination,
        start_date=trip.start_date,
        end_date=trip.end_date,
        budget=trip.budget,
        travelers=trip.travelers,
        interests=trip.interests or [],
        accommodation_preference=trip.accommodation_preference,
        pace=trip.pace,
        transport_mode=trip.transport_mode,
        xhs_source_enabled=bool(getattr(user, "xhs_source_enabled", False)),
        search_service=resolve_search_service_config(user),
        locale=getattr(user, "locale", None),
        planning_generated_at=planning_generated_at,
    )



def _resolve_llm_config(user: User | None, payload: dict) -> LlmConfig | None:
    payload_value = payload.get("llm_config")
    if isinstance(payload_value, dict):
        payload_config = LlmConfig.from_mapping(payload_value)
        if payload_config is not None:
            normalized_base_url = normalize_upstream_base_url(payload_config.base_url, settings)
            return payload_config.model_copy(update={"base_url": normalized_base_url}) if normalized_base_url else None

    if user is None:
        return None

    config = LlmConfig.from_mapping(
        {
            "base_url": user.llm_base_url,
            "api_key": user.llm_api_key,
            "model": user.llm_model,
            "wire_api": user.llm_wire_api,
            "provider_protocol": getattr(user, "llm_provider_protocol", None),
            "role_overrides": build_user_poi_role_overrides(user),
        }
    )
    if config is None:
        return None
    normalized_base_url = normalize_upstream_base_url(config.base_url, settings)
    return config.model_copy(update={"base_url": normalized_base_url}) if normalized_base_url else None



def _load_plan_from_trip(trip: Trip) -> PlanningResult | None:
    if not trip.itinerary_json:
        return None
    return PlanningResult(
        **trip.itinerary_json,
        trace=trip.latest_agent_trace_json or {"provider": "unknown", "workflow_id": "n/a", "notes": []},
    )



def _resolve_agent_provider(user: User | None) -> str:
    return normalize_agent_provider(getattr(user, "llm_agent_provider", None), default=normalize_agent_provider(settings.agent_provider))



def _emit_agent_progress(job_id: str, role_key: str, role_title: str, role_description: str, progress_percent: int) -> None:
    _transition_job(
        job_id,
        stage="route_planning",
        stage_message=f"{role_title}: {role_description}",
        progress_percent=progress_percent,
    )



def _persist_trip_plan(trip: Trip, plan: PlanningResult) -> dict:
    trip.itinerary_json = plan.model_dump(mode="json", exclude={"trace"})
    trip.latest_agent_trace_json = plan.trace.model_dump(mode="json")
    return trip.latest_agent_trace_json


def _image_enrichment_summary(plan: PlanningResult | None) -> dict[str, int]:
    counts = {"completed": 0, "pending": 0, "failed": 0, "skipped": 0}
    if plan is None:
        return counts
    for day in plan.days:
        for item in day.items:
            status = str(getattr(item, "image_status", "") or "").strip().lower()
            if status in counts:
                counts[status] += 1
    return counts


def _image_enrichment_debug_summary(plan: PlanningResult | None) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    if plan is None:
        return rows
    for day in plan.days:
        for item in day.items:
            if item.image_priority_tier in {None, "skipped"} and item.image_status != "failed" and not item.image_urls:
                continue
            rows.append(
                {
                    "item_id": item.id,
                    "name": item.name,
                    "status": item.image_status,
                    "priority_tier": item.image_priority_tier,
                    "failure_reason": item.image_failure_reason,
                    "image_count": len(item.image_urls or []),
                    "source_count": len(item.image_source_urls or []),
                }
            )
    return rows[:20]


def _image_enrichment_targets(plan: PlanningResult | None) -> list[dict[str, object]]:
    if plan is None:
        return []

    targets: list[dict[str, object]] = []
    for day in plan.days:
        for item_index, item in enumerate(day.items):
            if item.image_status != "pending":
                continue
            targets.append(
                {
                    "day_index": day.day_index,
                    "item_index": item_index,
                    "item_id": item.id,
                    "name": item.name,
                    "type": item.type,
                    "location": item.location,
                }
            )
    return targets


def _resolve_image_config(user: User | None) -> ImageModelConfig | None:
    if user is None:
        return None
    config = ImageModelConfig.from_mapping(
        {
            "base_url": getattr(user, "image_base_url", None),
            "api_key": getattr(user, "image_api_key", None),
            "model": getattr(user, "image_model", None),
            "provider": getattr(user, "image_provider", None),
        }
    )
    if config is None:
        return None
    normalized_base_url = normalize_upstream_base_url(config.base_url, settings)
    return config.model_copy(update={"base_url": normalized_base_url}) if normalized_base_url else None


def _read_local_asset_bytes(path_value: str) -> bytes:
    return settings.resolved_image_root.joinpath(path_value).read_bytes()



def _process_trip_generation(job: JobExecution) -> dict:
    log_job_event("trip_generate_started", job_id=job.id, logger_name=__name__, message="Starting trip generation job.")
    _transition_job(job.id, stage="brief_parsing", stage_message="Parsing trip brief.", progress_percent=10)
    with session_scope() as session:
        trip = session.query(Trip).filter(Trip.id == job.trip_id).one_or_none()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found for job")
        user = session.query(User).filter(User.id == trip.user_id).one_or_none()
        if _resolve_agent_provider(user) in {"helloagents", "langgraph"}:
            missing_poi_fields = user_poi_role_override_missing_fields(user)
            if missing_poi_fields:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail={
                        "code": "poi_llm_override_incomplete",
                        "message": "Complete POI base URL, API key, and model, or clear all POI model fields before generating with the selected backend workflow.",
                        "missing_fields": missing_poi_fields,
                    },
                )
        request = _build_request(trip, user)
        validate_trip_dates_for_generation(
            request.start_date,
            request.end_date,
            now=request.planning_generated_at,
        )
        orchestrator = build_orchestrator(
            settings,
            llm_config=_resolve_llm_config(user, job.payload),
            agent_provider=_resolve_agent_provider(user),
            enable_helloagents=True,
            progress_callback=lambda role_key, role_title, role_description, progress_percent: _emit_agent_progress(
                job.id,
                role_key,
                role_title,
                role_description,
                progress_percent,
            ),
        )
        orchestrator.set_execution_context(job_id=job.id)
        resume_checkpoint = job.payload.get("resume_checkpoint")
        set_resume_checkpoint = getattr(orchestrator, "set_resume_checkpoint", None)
        if callable(set_resume_checkpoint) and isinstance(resume_checkpoint, dict):
            set_resume_checkpoint(resume_checkpoint)

        _transition_job(job.id, stage="source_search", stage_message="Collecting grounded source inputs.", progress_percent=25)
        _transition_job(job.id, stage="source_scoring", stage_message="Scoring grounded source inputs.", progress_percent=45)
        _transition_job(job.id, stage="route_planning", stage_message="Drafting the itinerary route.", progress_percent=72)
        try:
            result = orchestrator.plan_trip(request)
        except JobCancelledError:
            raise
        except Exception as exc:
            get_resume_checkpoint = getattr(orchestrator, "get_resume_checkpoint", None)
            checkpoint = get_resume_checkpoint() if callable(get_resume_checkpoint) else None
            _record_trip_generation_resume_checkpoint(job.id, checkpoint, exc)
            raise
        _raise_if_cancelled(job.id)
        _transition_job(job.id, stage="hotel_matching", stage_message="Filling accommodation placeholders.", progress_percent=88)
        _transition_job(job.id, stage="export_ready", stage_message="Finalizing itinerary payload.", progress_percent=96)
        result = prepare_plan_images_for_async_enrichment(result)
        _raise_if_cancelled(job.id)
        agent_trace = _persist_trip_plan(trip, result)
        session.add(trip)
        session.flush()
        followup_job = create_job(
            session,
            job_type="trip.image_enrich",
            owner_user_id=trip.user_id,
            trip_id=trip.id,
            payload={"trip_id": trip.id},
        )
        return {
            "trip_id": trip.id,
            "summary": result.summary,
            "agent_trace": agent_trace,
            "image_enrichment_summary": _image_enrichment_summary(result),
            "image_enrichment_debug": _image_enrichment_debug_summary(result),
            "image_enrichment_targets": _image_enrichment_targets(result),
            "followup_job_id": followup_job.id,
        }



def _process_trip_refine(job: JobExecution) -> dict:
    log_job_event("trip_refine_started", job_id=job.id, logger_name=__name__, message="Starting trip refine job.")
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
        user = session.query(User).filter(User.id == trip.user_id).one_or_none()
        request = _build_request(trip, user)
        validate_trip_dates_for_generation(
            request.start_date,
            request.end_date,
            now=request.planning_generated_at,
        )
        orchestrator = build_orchestrator(
            settings,
            llm_config=_resolve_llm_config(user, job.payload),
            agent_provider=_resolve_agent_provider(user),
            enable_helloagents=False,
        )
        orchestrator.set_execution_context(job_id=job.id)

        _transition_job(job.id, stage="source_search", stage_message="Collecting context for refinement.", progress_percent=24)
        _transition_job(job.id, stage="source_scoring", stage_message="Scoring refinement context.", progress_percent=42)
        base_plan = _load_plan_from_trip(trip)
        if base_plan is None:
            _transition_job(job.id, stage="route_planning", stage_message="Generating a base itinerary before refinement.", progress_percent=64)
            base_plan = orchestrator.plan_trip(request)
        else:
            _transition_job(job.id, stage="route_planning", stage_message="Reworking the selected itinerary scope with the current itinerary as context.", progress_percent=64)
        refined_plan = orchestrator.refine_trip(
            request,
            base_plan,
            instruction=instruction,
            scope=scope,
            day_index=day_index,
        )
        _raise_if_cancelled(job.id)
        _transition_job(job.id, stage="hotel_matching", stage_message="Rebalancing stay placeholders after refinement.", progress_percent=86)
        _transition_job(job.id, stage="export_ready", stage_message="Finalizing refined itinerary payload.", progress_percent=96)
        refined_plan = prepare_plan_images_for_async_enrichment(refined_plan)
        _raise_if_cancelled(job.id)
        agent_trace = _persist_trip_plan(trip, refined_plan)
        session.add(trip)
        session.flush()
        followup_job = create_job(
            session,
            job_type="trip.image_enrich",
            owner_user_id=trip.user_id,
            trip_id=trip.id,
            payload={"trip_id": trip.id},
        )
        return {
            "trip_id": trip.id,
            "summary": refined_plan.summary,
            "instruction": instruction,
            "scope": scope,
            "day_index": day_index,
            "agent_trace": agent_trace,
            "image_enrichment_summary": _image_enrichment_summary(refined_plan),
            "image_enrichment_debug": _image_enrichment_debug_summary(refined_plan),
            "image_enrichment_targets": _image_enrichment_targets(refined_plan),
            "followup_job_id": followup_job.id,
        }


def _process_trip_image_enrichment(job: JobExecution) -> dict:
    log_job_event("trip_image_enrich_started", job_id=job.id, logger_name=__name__, message="Starting trip image enrichment job.")
    _transition_job(job.id, stage="source_search", stage_message="Preparing pending scenic stops for Tavily image search.", progress_percent=24)
    with session_scope() as session:
        trip = session.query(Trip).filter(Trip.id == job.trip_id).one_or_none()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found for job")
        user = session.query(User).filter(User.id == trip.user_id).one_or_none()
        request = _build_request(trip, user)
        plan = _load_plan_from_trip(trip)
        if plan is None:
            raise HTTPException(status_code=400, detail="Generate itinerary before enriching images")
        _transition_job(job.id, stage="route_planning", stage_message="Searching Tavily image sources and writing images back.", progress_percent=68)
        enriched_plan = enrich_plan_images(
            plan,
            request,
            search_service=request.search_service,
            force=bool(job.payload.get("force", False)),
            review_config=_resolve_llm_config(user, job.payload),
        )
        _raise_if_cancelled(job.id)
        _transition_job(job.id, stage="export_ready", stage_message="Persisting enriched itinerary images.", progress_percent=96)
        agent_trace = _persist_trip_plan(trip, enriched_plan)
        session.add(trip)
        session.flush()
        return {
            "trip_id": trip.id,
            "summary": enriched_plan.summary,
            "agent_trace": agent_trace,
            "image_enrichment_summary": _image_enrichment_summary(enriched_plan),
            "image_enrichment_debug": _image_enrichment_debug_summary(enriched_plan),
            "image_enrichment_targets": _image_enrichment_targets(enriched_plan),
        }



def _process_pdf_export(job: JobExecution) -> dict:
    log_job_event("trip_export_started", job_id=job.id, logger_name=__name__, message="Starting export job.")
    _transition_job(job.id, stage="brief_parsing", stage_message="Preparing itinerary export input.", progress_percent=18)
    with session_scope() as session:
        trip = session.query(Trip).filter(Trip.id == job.trip_id).one_or_none()
        if not trip:
            raise HTTPException(status_code=404, detail="Trip not found for job")
        if not trip.itinerary_json:
            raise HTTPException(status_code=400, detail="Generate itinerary before export")
        user = session.query(User).filter(User.id == trip.user_id).one_or_none()
        orchestrator = build_orchestrator(
            settings,
            llm_config=_resolve_llm_config(user, job.payload),
            agent_provider=_resolve_agent_provider(user),
            enable_helloagents=False,
        )
        orchestrator.set_execution_context(job_id=job.id)
        request = _build_request(trip, user)
        plan = _load_plan_from_trip(trip)
        if plan is None:
            raise HTTPException(status_code=400, detail="Generate itinerary before export")
        formats = normalize_export_formats(list(job.payload.get("formats") or []))
        _transition_job(job.id, stage="export_ready", stage_message="Rendering export artifacts.", progress_percent=82)
        draft = orchestrator.draft_export_payload(request, plan)
        _raise_if_cancelled(job.id)
        export_result = write_export_bundle(job.id, request, plan, draft, settings, formats=formats)
        _raise_if_cancelled(job.id)
        return export_result


def _process_image_generation(job: JobExecution) -> dict:
    log_job_event("image_generate_started", job_id=job.id, logger_name=__name__, message="Starting image generation job.")
    generation_id = str(job.payload.get("generation_id") or "").strip()
    if not generation_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "invalid_image_generation_job", "message": "generation_id is required"},
        )

    _transition_job(job.id, stage="prompt_compose", stage_message="Finalizing image prompt payload.", progress_percent=16)
    with session_scope() as session:
        generation = session.query(ImageGeneration).filter(ImageGeneration.id == generation_id).one_or_none()
        if generation is None:
            raise HTTPException(status_code=404, detail={"code": "image_generation_not_found", "message": "Image generation not found"})
        user = session.query(User).filter(User.id == generation.user_id).one_or_none()
        image_config = _resolve_image_config(user)
        if image_config is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"code": "image_provider_not_configured", "message": "Configure image model settings before generating images."},
            )

        generation.status = "running"
        session.add(generation)
        session.flush()

        compose_result = compose_image_prompt(
            ImagePromptComposePayload(
                title=generation.title,
                destination=generation.destination,
                scene_prompt=generation.scene_prompt,
                prompt=generation.prompt,
                negative_prompt=generation.negative_prompt or "",
                style_tags=list(generation.style_tags_json or []),
                reference_urls=[str(item.get("url") or "").strip() for item in generation.reference_images_json if isinstance(item, dict)],
                reference_count=len(generation.reference_images_json or []),
            ),
            _resolve_llm_config(user, {}),
        )
        generation.title = compose_result.title or generation.title
        generation.optimized_prompt = generation.optimized_prompt or compose_result.optimized_prompt
        generation.negative_prompt = generation.negative_prompt or compose_result.negative_prompt
        generation.provider = image_config.provider
        generation.model = image_config.model
        session.add(generation)
        session.commit()

        _transition_job(job.id, stage="source_prepare", stage_message="Preparing uploaded image assets.", progress_percent=34)
        source_asset = (generation.source_images_json or [None])[0]
        source_bytes: bytes | None = None
        source_filename: str | None = None
        source_mime_type: str | None = None
        if isinstance(source_asset, dict) and source_asset.get("path"):
            source_bytes = _read_local_asset_bytes(str(source_asset["path"]))
            source_filename = str(source_asset.get("filename") or "source.png")
            source_mime_type = str(source_asset.get("mime_type") or "image/png")

        _transition_job(job.id, stage="image_generate", stage_message="Calling the configured image model.", progress_percent=72)
        provider = build_image_provider(image_config)
        generated = provider.generate(
            ImageProviderRequest(
                mode=generation.mode,
                prompt=generation.optimized_prompt or generation.prompt,
                negative_prompt=generation.negative_prompt,
                source_image_bytes=source_bytes,
                source_image_filename=source_filename,
                source_image_mime_type=source_mime_type,
                reference_image_urls=[str(item.get("url") or "").strip() for item in generation.reference_images_json if isinstance(item, dict)],
            )
        )

        _raise_if_cancelled(job.id)
        _transition_job(job.id, stage="asset_persist", stage_message="Persisting generated image assets.", progress_percent=90)
        persisted_assets = [
            persist_bytes(
                image.data,
                settings=settings,
                bucket="generated",
                owner_user_id=generation.user_id,
                filename="generated.png",
                mime_type=image.mime_type,
            )
            for image in generated
        ]
        generation.result_images_json = persisted_assets
        generation.status = "completed"
        if generation.visibility == "public":
            generation.published_at = generation.published_at or _utcnow()
        session.add(generation)
        session.flush()
        return {
            "generation_id": generation.id,
            "result_images": persisted_assets,
            "visibility": generation.visibility,
        }



def process_job(job_id: str, *, retry_transient: bool = False) -> None:
    job = _claim_job(job_id)
    if not job:
        return

    token = set_current_job_id(job.id)
    try:
        log_job_event("job_processing_started", job_id=job.id, logger_name=__name__, message=f"Processing job type {job.type}.", job_type=job.type)
        followup_job_id: str | None = None
        if job.type == "trip.generate":
            result = _process_trip_generation(job)
            completion_message = "Itinerary ready for review and export."
        elif job.type == "trip.refine":
            result = _process_trip_refine(job)
            completion_message = "Refined itinerary ready for review and export."
        elif job.type == "trip.image_enrich":
            result = _process_trip_image_enrichment(job)
            completion_message = "Itinerary image enrichment ready."
        elif job.type == "export.pdf":
            result = _process_pdf_export(job)
            completion_message = "Export artifacts ready."
        elif job.type == "image.generate":
            result = _process_image_generation(job)
            completion_message = "Image generation ready."
        else:
            raise RuntimeError(f"Unsupported job type: {job.type}")
        if isinstance(result, dict):
            followup_job_id = str(result.get("followup_job_id") or "").strip() or None
        _raise_if_cancelled(job.id)
        _mark_complete(job.id, result, stage="export_ready", stage_message=completion_message)
        if followup_job_id:
            _raise_if_cancelled(job.id)
            dispatch_job_now(followup_job_id, settings)
    except JobCancelledError:
        log_job_event("job_cancelled_observed", job_id=job.id, logger_name=__name__, message="Job processing stopped because the job was cancelled.")
    except Exception as exc:  # pragma: no cover
        if retry_transient:
            retry_delay = _schedule_retry(job.id, exc)
            if retry_delay is not None:
                log_job_event(
                    "job_retry_scheduled",
                    job_id=job.id,
                    logger_name=__name__,
                    message=f"Retrying transient job failure in {retry_delay} seconds.",
                    attempt_count=job.attempt_count,
                    max_attempts=job.max_attempts,
                )
                raise JobRetryRequested(retry_delay) from exc
        _mark_failed(job.id, _extract_error_message(exc))
        _LOGGER.exception("Job processing failed", extra={"job_id": job.id})
    finally:
        reset_current_job_id(token)
