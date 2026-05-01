from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_DATA_ROOT = _REPO_ROOT / "storage" / "xhs-crawler"


class Settings(BaseSettings):
    host: str = "0.0.0.0"
    port: int = 8090
    data_root: str = str(_DEFAULT_DATA_ROOT)
    node_binary: str = "node"
    node_min_major: int = 21
    opencli_binary: str = "opencli"
    opencli_timeout_seconds: int = 45
    xhs_bind_start_command: list[str] = ["opencli", "travelmind-xhs", "bind", "start"]
    xhs_bind_poll_command: list[str] = ["opencli", "travelmind-xhs", "bind", "poll"]
    xhs_search_command: list[str] = ["opencli", "travelmind-xhs", "search"]
    xhs_note_command: list[str] = ["opencli", "travelmind-xhs", "note"]
    log_level: str = "info"

    model_config = SettingsConfigDict(env_prefix="TRAVELMIND_XHS_", extra="ignore")
