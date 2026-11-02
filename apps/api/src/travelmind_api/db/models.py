from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, Date, DateTime, Float, ForeignKey, Index, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from travelmind_api.core.credentials import EncryptedCredential
from travelmind_api.core.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    locale: Mapped[str] = mapped_column(String(16), default="zh-CN")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    llm_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    llm_api_key: Mapped[str | None] = mapped_column(EncryptedCredential(), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    llm_wire_api: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_provider_protocol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_agent_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    poi_llm_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    poi_llm_api_key: Mapped[str | None] = mapped_column(EncryptedCredential(), nullable=True)
    poi_llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    weather_llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hotel_llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transport_llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    poi_llm_wire_api: Mapped[str | None] = mapped_column(String(64), nullable=True)
    poi_llm_provider_protocol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_api_key: Mapped[str | None] = mapped_column(EncryptedCredential(), nullable=True)
    image_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    search_service_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    search_service_transport: Mapped[str | None] = mapped_column(String(32), nullable=True)
    search_service_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    search_service_api_key: Mapped[str | None] = mapped_column(EncryptedCredential(), nullable=True)
    search_service_timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    xhs_source_enabled: Mapped[bool] = mapped_column(default=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


    generation_quota: Mapped["GenerationQuota | None"] = relationship(
        lazy="selectin", uselist=False, cascade="all, delete-orphan"
    )


class GenerationQuota(Base):
    """An opt-in, persistent allowance; ordinary accounts have no quota row."""

    __tablename__ = "generation_quotas"
    __table_args__ = (
        CheckConstraint("generation_limit >= 0", name="ck_generation_quota_limit"),
        CheckConstraint("used >= 0 AND used <= generation_limit", name="ck_generation_quota_used"),
    )

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    generation_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class XhsAccountSession(Base):
    __tablename__ = "xhs_account_sessions"

    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="unbound")
    xhs_user_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    session_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    session_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class XhsBindingAttempt(Base):
    __tablename__ = "xhs_binding_attempts"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    verification_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    verification_code: Mapped[str | None] = mapped_column(String(255), nullable=True)
    qr_image_data_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    origin: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    destination: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    budget: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    travelers: Mapped[int] = mapped_column(nullable=False, default=1)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    accommodation_preference: Mapped[str] = mapped_column(Text, default="")
    pace: Mapped[str] = mapped_column(String(32), default="balanced")
    transport_mode: Mapped[str] = mapped_column(String(32), default="mixed")
    itinerary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latest_agent_trace_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TripRefineSession(Base):
    __tablename__ = "trip_refine_sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trip_id: Mapped[str] = mapped_column(String(32), ForeignKey("trips.id"), nullable=False, unique=True, index=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    messages_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    uploaded_guides_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    community_sources_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class CommunityPost(Base):
    __tablename__ = "community_posts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    trip_id: Mapped[str] = mapped_column(String(32), ForeignKey("trips.id"), nullable=False, unique=True, index=True)
    author_user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    share_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cover_image_url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    source_trip_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobRecord(Base):
    __tablename__ = "job_records"
    __table_args__ = (
        Index("ix_job_records_idempotency", "owner_user_id", "type", "idempotency_key", unique=True),
        Index("ix_job_records_recovery", "status", "heartbeat_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    owner_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    trip_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("trips.id"), nullable=True, index=True)
    workflow_run_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("workflow_runs.id"), nullable=True, index=True
    )
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeline_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_owner_trip", "owner_user_id", "trip_id"),
        Index("ix_workflow_runs_status", "status", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    owner_user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False)
    trip_id: Mapped[str] = mapped_column(String(32), ForeignKey("trips.id"), nullable=False)
    original_job_id: Mapped[str] = mapped_column(String(40), nullable=False)
    current_job_id: Mapped[str] = mapped_column(String(40), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(64), nullable=False)
    state_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    input_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    expected_trip_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_node: Mapped[str | None] = mapped_column(String(64), nullable=True)
    committed_job_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ImageGeneration(Base):
    __tablename__ = "image_generations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    destination: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    scene_prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="text_to_image")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="private")
    prompt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    optimized_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    negative_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    style_tags_json: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_images_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    reference_images_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    result_images_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remix_from_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("image_generations.id"), nullable=True, index=True)
    remix_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_logs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    admin_user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), nullable=False, index=True)
    admin_email_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
