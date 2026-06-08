import os
import shutil
import sys
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

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

    for name in list(sys.modules):
        if name.startswith("travelmind_api"):
            del sys.modules[name]

    from travelmind_api.main import create_app

    app = create_app()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        shutil.rmtree(case_root, ignore_errors=True)
