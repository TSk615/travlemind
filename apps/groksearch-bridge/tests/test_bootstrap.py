import shutil
from pathlib import Path
from uuid import uuid4

import travelmind_groksearch_bridge.bootstrap as bootstrap


def _case_root() -> Path:
    root = Path(__file__).resolve().parents[3] / ".tmp" / "groksearch-bootstrap-tests" / uuid4().hex
    root.mkdir(parents=True, exist_ok=True)
    return root


def test_build_setup_report_detects_missing_command_and_auth(monkeypatch):
    case_root = _case_root()
    monkeypatch.setattr(bootstrap, "_project_root", lambda: case_root)
    monkeypatch.delenv("TRAVELMIND_GROKSEARCH_COMMAND", raising=False)
    monkeypatch.delenv("GUDA_API_KEY", raising=False)
    monkeypatch.delenv("GROK_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    try:
        report = bootstrap.build_setup_report()

        assert report.ok is False
        assert any("未找到上游 GrokSearch 命令" in item for item in report.errors)
        assert any("缺少上游鉴权" in item for item in report.errors)
        assert any("TAVILY_API_KEY" in item for item in report.warnings)
    finally:
        shutil.rmtree(case_root, ignore_errors=True)


def test_build_setup_report_reads_root_env(monkeypatch):
    case_root = _case_root()
    dotenv_path = case_root / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "TRAVELMIND_GROKSEARCH_COMMAND=python",
                "GUDA_API_KEY=test-guda-key",
                "TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY=bridge-key",
                "TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL=http://127.0.0.1:8085/mcp",
                "TAVILY_ENABLED=false",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(bootstrap, "_project_root", lambda: case_root)

    try:
        report = bootstrap.build_setup_report()

        assert report.ok is True
        assert report.command == "python"
        assert report.command_path is not None
        assert any("Upstream auth: GUDA_API_KEY" in item for item in report.info)
    finally:
        shutil.rmtree(case_root, ignore_errors=True)


def test_build_env_template_mentions_required_keys():
    template = bootstrap.build_env_template()

    assert "TRAVELMIND_GROKSEARCH_COMMAND=grok-search" in template
    assert "GUDA_API_KEY=" in template
    assert "GROK_API_KEY=" in template
    assert "EXA_API_KEY=" in template
    assert "TRAVELMIND_GROKSEARCH_RUNNER_MODE=inprocess" in template
    assert "TRAVELMIND_GROKSEARCH_BRIDGE_TIMEOUT_SECONDS=75" in template
