import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

TEST_TMP_ROOT = Path(__file__).resolve().parents[3] / "storage" / ".pytest_tmp" / "api"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)

LLM_ENV_VARS = [
    "TRAVELMIND_LLM_BASE_URL",
    "TRAVELMIND_LLM_API_KEY",
    "TRAVELMIND_LLM_MODEL",
    "TRAVELMIND_LLM_TIMEOUT_SECONDS",
    "TRAVELMIND_LLM_WIRE_API",
    "OPENAI_BASE_URL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_WIRE_API",
]

INTEGRATION_ENV_VARS = [
    "TRAVELMIND_SEARCH_SERVICE_PROVIDER",
    "TRAVELMIND_SEARCH_SERVICE_TRANSPORT",
    "TRAVELMIND_MCP_BASE_URL",
    "TRAVELMIND_MCP_API_KEY",
    "TRAVELMIND_MCP_SERVER_API_KEY",
    "TRAVELMIND_MCP_TIMEOUT_SECONDS",
    "TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL",
    "TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY",
    "TRAVELMIND_GROKSEARCH_BRIDGE_TIMEOUT_SECONDS",
    "TRAVELMIND_TAVILY_BASE_URL",
    "TRAVELMIND_TAVILY_API_KEY",
    "TRAVELMIND_TAVILY_TIMEOUT_SECONDS",
    "TAVILY_API_KEY",
    "TAVILY_API_URL",
    "TRAVELMIND_EXA_POOL_BASE_URL",
    "TRAVELMIND_EXA_POOL_API_KEY",
    "TRAVELMIND_EXA_POOL_TIMEOUT_SECONDS",
    "TRAVELMIND_XHS_CRAWLER_ENABLED",
    "TRAVELMIND_XHS_CRAWLER_BASE_URL",
    "TRAVELMIND_XHS_CRAWLER_API_KEY",
    "TRAVELMIND_XHS_CRAWLER_TIMEOUT_SECONDS",
    "TRAVELMIND_XHS_CACHE_TTL_SECONDS",
    "TRAVELMIND_XHS_LIMIT_PER_QUERY",
    "TRAVELMIND_XHS_MAX_RESULTS",
    "TRAVELMIND_UPSTREAM_PRIVATE_URL_POLICY",
    "TRAVELMIND_UPSTREAM_URL_ALLOWED_HOSTS",
    "TRAVELMIND_GROK_LLM_BASE_URL",
    "TRAVELMIND_GROK_LLM_API_KEY",
    "TRAVELMIND_GROK_LLM_MODEL",
    "TRAVELMIND_GROK_LLM_PROVIDER_PROTOCOL",
    "TRAVELMIND_GROK_LLM_PROTOCOL",
    "TRAVELMIND_GROK_LLM_WIRE_API",
    "TRAVELMIND_GROK_LLM_TIMEOUT_SECONDS",
    "GROK_API_URL",
    "GROK_API_KEY",
    "GROK_MODEL",
]
@pytest.fixture(autouse=True)
def clear_integration_env(monkeypatch):
    for variable in INTEGRATION_ENV_VARS:
        monkeypatch.setenv(variable, "")

@pytest.fixture()
def client(monkeypatch):
    case_root = TEST_TMP_ROOT / f"case-{uuid.uuid4().hex}"
    export_root = case_root / "exports"
    export_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("TRAVELMIND_DATABASE_URL", f"sqlite:///{(case_root / 'travelmind.db').as_posix()}")
    monkeypatch.setenv("TRAVELMIND_WORKFLOW_CHECKPOINT_URL", str(case_root / "langgraph-checkpoints.db"))
    monkeypatch.setenv("TRAVELMIND_ENVIRONMENT", "test")
    monkeypatch.setenv("TRAVELMIND_CSRF_ENABLED", "false")
    monkeypatch.setenv("TRAVELMIND_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("TRAVELMIND_EXPORT_ROOT", str(export_root))
    monkeypatch.setenv("TRAVELMIND_QUEUE_MODE", "inline")
    monkeypatch.setenv("TRAVELMIND_AGENT_PROVIDER", "stub")
    monkeypatch.setenv("TRAVELMIND_PUBLIC_API_URL", "http://testserver")
    for variable in LLM_ENV_VARS:
        monkeypatch.delenv(variable, raising=False)
    for variable in INTEGRATION_ENV_VARS:
        monkeypatch.setenv(variable, "")
    for variable in list(os.environ):
        if variable.startswith("TRAVELMIND_LLM_ROLE_"):
            monkeypatch.delenv(variable, raising=False)

    # Keep one coherent module graph for the whole pytest process. Removing
    # travelmind_api from sys.modules left test modules holding stale function
    # objects, so later monkeypatches targeted a different module instance.
    # Rebind the process-wide settings and session factory instead; the client
    # fixture is the only place that owns a test database lifecycle.
    from travelmind_api.core.config import get_settings
    from travelmind_api.core import database

    get_settings.cache_clear()
    test_settings = get_settings()
    database.engine.dispose()
    database.settings = test_settings
    database.connect_args = (
        {"check_same_thread": False, "timeout": 30}
        if test_settings.database_url.startswith("sqlite")
        else {}
    )
    database.engine = create_engine(
        test_settings.database_url,
        connect_args=database.connect_args,
        future=True,
        pool_pre_ping=True,
    )
    database.SessionLocal.configure(bind=database.engine)

    import travelmind_api.jobs.handlers as job_handlers
    import travelmind_api.main as main_module

    job_handlers.settings = test_settings
    main_module.settings = test_settings

    app = main_module.create_app()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        database.engine.dispose()
        get_settings.cache_clear()
        shutil.rmtree(case_root, ignore_errors=True)
