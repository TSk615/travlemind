from __future__ import annotations

from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect, text

from travelmind_api.core.database import alembic_config


def _sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_alembic_upgrades_an_empty_database(tmp_path: Path):
    database_path = tmp_path / "empty.db"
    database_url = _sqlite_url(database_path)

    command.upgrade(alembic_config(database_url), "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert {
        "alembic_version",
        "users",
        "trips",
        "trip_refine_sessions",
        "community_posts",
        "job_records",
        "workflow_runs",
        "image_generations",
        "admin_audit_logs",
    }.issubset(set(inspector.get_table_names()))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0006_generation_quotas"
    assert "workflow_run_id" in {column["name"] for column in inspector.get_columns("job_records")}


def test_alembic_absorbs_a_legacy_database(tmp_path: Path):
    database_path = tmp_path / "legacy.db"
    database_url = _sqlite_url(database_path)
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id VARCHAR(32) PRIMARY KEY, email VARCHAR(255), name VARCHAR(120), password_hash VARCHAR(255), created_at DATETIME)"))
        connection.execute(text("CREATE TABLE trips (id VARCHAR(32) PRIMARY KEY, user_id VARCHAR(32), title VARCHAR(255), destination VARCHAR(255), start_date DATE, end_date DATE, budget FLOAT, travelers INTEGER, interests JSON, accommodation_preference TEXT, pace VARCHAR(32), transport_mode VARCHAR(32), itinerary_json JSON, latest_agent_trace_json JSON, created_at DATETIME, updated_at DATETIME)"))
        connection.execute(text("CREATE TABLE job_records (id VARCHAR(40) PRIMARY KEY, type VARCHAR(64), status VARCHAR(32), owner_user_id VARCHAR(32), trip_id VARCHAR(32), payload_json JSON, result_json JSON, error_message TEXT, created_at DATETIME, updated_at DATETIME, started_at DATETIME, finished_at DATETIME)"))

    command.upgrade(alembic_config(database_url), "head")

    inspector = inspect(engine)
    assert "origin" in {column["name"] for column in inspector.get_columns("trips")}
    assert str(next(column["type"] for column in inspector.get_columns("trips") if column["name"] == "budget")).startswith("NUMERIC")
    assert {"stage", "stage_message", "progress_percent", "timeline_json"}.issubset(
        {column["name"] for column in inspector.get_columns("job_records")}
    )
    assert {"idempotency_key", "attempt_count", "max_attempts", "heartbeat_at"}.issubset(
        {column["name"] for column in inspector.get_columns("job_records")}
    )
    assert "workflow_run_id" in {column["name"] for column in inspector.get_columns("job_records")}
    assert "workflow_runs" in inspector.get_table_names()
    assert {"llm_api_key", "search_service_api_key", "disabled_at"}.issubset(
        {column["name"] for column in inspector.get_columns("users")}
    )
    assert "trip_refine_sessions" in inspector.get_table_names()
    assert "admin_audit_logs" in inspector.get_table_names()


def test_workflow_run_migration_can_downgrade_and_reapply(tmp_path: Path):
    database_url = _sqlite_url(tmp_path / "workflow-migration.db")
    config = alembic_config(database_url)
    command.upgrade(config, "head")
    command.downgrade(config, "0004_search_role_models")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "workflow_runs" not in inspector.get_table_names()
    assert "workflow_run_id" not in {column["name"] for column in inspector.get_columns("job_records")}

    command.upgrade(config, "head")
    inspector = inspect(engine)
    assert "workflow_runs" in inspector.get_table_names()
    assert "workflow_run_id" in {column["name"] for column in inspector.get_columns("job_records")}
