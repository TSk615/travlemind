from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


@lru_cache(maxsize=1)
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


def get_env(key: str, default: str | None = None) -> str | None:
    if key in os.environ:
        return os.environ.get(key)
    return _dotenv_values().get(key, default)


def load_into_process_env(*keys: str) -> None:
    for key in keys:
        if key in os.environ:
            continue
        value = _dotenv_values().get(key)
        if value is not None:
            os.environ[key] = value
