from __future__ import annotations

import os

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from travelmind_api.core.database import alembic_config


POSTGRES_URL = os.getenv("TRAVELMIND_TEST_POSTGRES_URL", "").strip()


@pytest.mark.skipif(not POSTGRES_URL, reason="TRAVELMIND_TEST_POSTGRES_URL is not configured")
def test_postgres_upgrade_downgrade_cycle():
    config = alembic_config(POSTGRES_URL)
    command.upgrade(config, "head")

    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    inspector = inspect(engine)
    assert {"users", "trips", "job_records", "alembic_version"}.issubset(inspector.get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "0003_trip_budget_numeric"

    command.downgrade(config, "base")
    assert "users" not in inspect(engine).get_table_names()
    command.upgrade(config, "head")
    assert "users" in inspect(engine).get_table_names()
