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
