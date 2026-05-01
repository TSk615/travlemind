from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _dotenv_values() -> dict[str, str]:
    dotenv_path = _project_root() / ".env"
    values: dict[str, str] = {}
    if not dotenv_path.exists():
        return values
    for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def get_setting(key: str, default: str | None = None) -> str | None:
    if key in os.environ:
        return os.environ.get(key)
    return _dotenv_values().get(key, default)


def _truthy(value: str | None, *, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _split_command(command: str) -> list[str]:
    return shlex.split(command, posix=os.name != "nt")


def resolve_command_path(command: str) -> str | None:
    try:
        parts = _split_command(command)
    except ValueError:
        return None
    if not parts:
        return None
    candidate = parts[0].strip()
    if not candidate:
        return None
    resolved = shutil.which(candidate)
    if resolved:
        return resolved
    script_dir = Path(sys.executable).resolve().parent
    for sibling in _candidate_executable_paths(script_dir, candidate):
        if sibling.exists():
            return str(sibling)
    local_venv_dir = _project_root() / "apps" / "groksearch-bridge" / ".venv" / "Scripts"
    for sibling in _candidate_executable_paths(local_venv_dir, candidate):
        if sibling.exists():
            return str(sibling)
    path = Path(candidate).expanduser()
    if path.exists():
        return str(path.resolve())
    return None


def _candidate_executable_paths(directory: Path, candidate: str) -> list[Path]:
    normalized = candidate.strip()
    if not normalized:
        return []
    paths = [directory / normalized]
    if os.name == "nt" and not normalized.lower().endswith(".exe"):
        paths.append(directory / f"{normalized}.exe")
    return paths


@dataclass
class SetupReport:
    command: str
    command_path: str | None
    env_file_path: Path
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def build_setup_report() -> SetupReport:
    command = str(get_setting("TRAVELMIND_GROKSEARCH_COMMAND", "grok-search") or "grok-search").strip()
    report = SetupReport(
        command=command,
        command_path=resolve_command_path(command),
        env_file_path=_project_root() / ".env",
    )

    if not report.command_path:
        report.errors.append(
            "未找到上游 GrokSearch 命令。请先安装上游包，或者把 `TRAVELMIND_GROKSEARCH_COMMAND` 指向可执行命令。"
        )
    else:
        report.info.append(f"GrokSearch command: {report.command}")
        report.info.append(f"Resolved path: {report.command_path}")

    if not (get_setting("GUDA_API_KEY") or get_setting("GROK_API_KEY")):
        report.errors.append("缺少上游鉴权。请至少配置 `GUDA_API_KEY` 或 `GROK_API_KEY`。")
    else:
        auth_source = "GUDA_API_KEY" if get_setting("GUDA_API_KEY") else "GROK_API_KEY"
        report.info.append(f"Upstream auth: {auth_source}")

    if _truthy(get_setting("TAVILY_ENABLED", "true"), default=True) and not get_setting("TAVILY_API_KEY"):
        report.warnings.append("`TAVILY_ENABLED=true` 但未配置 `TAVILY_API_KEY`，`web_fetch` / `web_map` 能力会受限。")

    if not get_setting("TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY"):
        report.warnings.append("未配置 `TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY`，bridge 启动时会缺少鉴权配置。")

    if not get_setting("TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL"):
        report.warnings.append("未配置 `TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL`，api/worker 默认不会自动指向本地 bridge。")

    return report


def install_upstream_groksearch(*, git_url: str, git_ref: str, force_reinstall: bool = False) -> None:
    package_spec = f"git+{git_url}@{git_ref}"
    uv_binary = shutil.which("uv")
    if uv_binary:
        command = [uv_binary, "pip", "install", "--python", sys.executable]
    else:
        command = [sys.executable, "-m", "pip", "install", "--no-cache-dir"]
    if force_reinstall:
        command.extend(["--upgrade", "--force-reinstall"])
    command.append(package_spec)
    print(f"[bootstrap] Installing upstream GrokSearch from {package_spec}")
    subprocess.run(command, check=True)


def build_env_template() -> str:
    return "\n".join(
        [
            "# GrokSearch local setup",
            "TRAVELMIND_GROKSEARCH_COMMAND=grok-search",
            "TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY=change-this-bridge-key",
            "TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL=http://127.0.0.1:8085/mcp",
            "TRAVELMIND_GROKSEARCH_BRIDGE_TIMEOUT_SECONDS=30",
            "TRAVELMIND_SEARCH_SERVICE_PROVIDER=groksearch",
            "TRAVELMIND_SEARCH_SERVICE_TRANSPORT=mcp",
            "",
            "# Upstream GrokSearch auth: configure one of the following",
            "GUDA_API_KEY=",
            "GROK_API_KEY=",
            "GROK_API_URL=",
            "GROK_MODEL=grok-4.20-beta",
            "",
            "# Optional enrichers",
            "TAVILY_ENABLED=true",
            "TAVILY_API_KEY=",
            "TAVILY_API_URL=",
            "FIRECRAWL_API_KEY=",
            "FIRECRAWL_API_URL=",
        ]
    )


def print_report(report: SetupReport) -> None:
    print(f"[bootstrap] Root .env path: {report.env_file_path}")
    for item in report.info:
        print(f"[ok] {item}")
    for item in report.warnings:
        print(f"[warn] {item}")
    for item in report.errors:
        print(f"[error] {item}")
    print(f"[bootstrap] Result: {'ready' if report.ok else 'not ready'}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Install and validate local GrokSearch bridge prerequisites.")
    parser.add_argument("--install-upstream", action="store_true", help="Install upstream GrokSearch into the current bridge virtual environment.")
    parser.add_argument("--force-reinstall", action="store_true", help="Force reinstall upstream GrokSearch when used with --install-upstream.")
    parser.add_argument("--check", action="store_true", help="Validate command resolution and required environment variables.")
    parser.add_argument("--print-env-template", action="store_true", help="Print a root .env snippet for local GrokSearch setup.")
    parser.add_argument(
        "--groksearch-git-url",
        default=str(get_setting("GROKSEARCH_GIT_URL", "https://github.com/GuDaStudio/GrokSearch")),
        help="Git URL used when installing upstream GrokSearch.",
    )
    parser.add_argument(
        "--groksearch-ref",
        default=str(get_setting("GROKSEARCH_REF", "grok-with-tavily")),
        help="Git ref used when installing upstream GrokSearch.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.print_env_template:
        print(build_env_template())

    if args.install_upstream:
        install_upstream_groksearch(
            git_url=args.groksearch_git_url,
            git_ref=args.groksearch_ref,
            force_reinstall=bool(args.force_reinstall),
        )

    should_check = args.check or not any((args.install_upstream, args.print_env_template))
    if should_check:
        report = build_setup_report()
        print_report(report)
        return 0 if report.ok else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
