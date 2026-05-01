from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, inspect, text
from sqlalchemy.orm import Mapped, mapped_column

from travelmind_api.core.database import Base, engine


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
    llm_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    llm_wire_api: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_agent_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    image_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    image_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    image_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    search_service_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    search_service_transport: Mapped[str | None] = mapped_column(String(32), nullable=True)
    search_service_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    search_service_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_service_timeout_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    xhs_source_enabled: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    budget: Mapped[float] = mapped_column(Float, nullable=False)
    travelers: Mapped[int] = mapped_column(nullable=False, default=1)
    interests: Mapped[list[str]] = mapped_column(JSON, default=list)
    accommodation_preference: Mapped[str] = mapped_column(Text, default="")
    pace: Mapped[str] = mapped_column(String(32), default="balanced")
    transport_mode: Mapped[str] = mapped_column(String(32), default="mixed")
    itinerary_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    latest_agent_trace_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
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

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    owner_user_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    trip_id: Mapped[str | None] = mapped_column(String(32), ForeignKey("trips.id"), nullable=True, index=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    stage_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    timeline_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


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


# Lightweight SQLite compatibility for local developer databases created before
# the LLM config fields existed. Fresh databases still rely on create_all().
def _ensure_sqlite_user_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        inspector = inspect(conn)
        if "users" not in inspector.get_table_names():
            return

        existing_columns = {column["name"] for column in inspector.get_columns("users")}
        statements: list[str] = []
        if "llm_base_url" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN llm_base_url VARCHAR(512)")
        if "llm_api_key" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN llm_api_key TEXT")
        if "llm_model" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN llm_model VARCHAR(255)")
        if "llm_wire_api" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN llm_wire_api VARCHAR(64)")
        if "llm_agent_provider" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN llm_agent_provider VARCHAR(64)")
        if "image_base_url" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN image_base_url VARCHAR(512)")
        if "image_api_key" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN image_api_key TEXT")
        if "image_model" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN image_model VARCHAR(255)")
        if "image_provider" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN image_provider VARCHAR(64)")
        if "search_service_provider" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN search_service_provider VARCHAR(64)")
        if "search_service_transport" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN search_service_transport VARCHAR(32)")
        if "search_service_base_url" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN search_service_base_url VARCHAR(512)")
        if "search_service_api_key" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN search_service_api_key TEXT")
        if "search_service_timeout_seconds" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN search_service_timeout_seconds FLOAT NOT NULL DEFAULT 30")
        if "xhs_source_enabled" not in existing_columns:
            statements.append("ALTER TABLE users ADD COLUMN xhs_source_enabled BOOLEAN NOT NULL DEFAULT 0")

        for statement in statements:
            conn.execute(text(statement))


_ensure_sqlite_user_columns()


def _ensure_sqlite_trip_columns() -> None:
    if engine.dialect.name != "sqlite":
        return

    with engine.begin() as conn:
        inspector = inspect(conn)
        if "trips" not in inspector.get_table_names():
            return

        existing_columns = {column["name"] for column in inspector.get_columns("trips")}
        statements: list[str] = []
        if "origin" not in existing_columns:
            statements.append("ALTER TABLE trips ADD COLUMN origin VARCHAR(255) NOT NULL DEFAULT ''")

        for statement in statements:
            conn.execute(text(statement))


_ensure_sqlite_trip_columns()
