from __future__ import annotations

import json
import logging
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Any

from travelmind_api.core.config import Settings, get_settings

_current_job_id: ContextVar[str | None] = ContextVar("travelmind_current_job_id", default=None)
_jsonl_write_lock = Lock()
_configured = False
_CONFIGURED_HANDLER_MARKER = "_travelmind_file_logging"


class _JobContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "job_id"):
            record.job_id = _current_job_id.get() or "-"
        return True


def set_current_job_id(job_id: str | None) -> Token:
    return _current_job_id.set(job_id)


def reset_current_job_id(token: Token) -> None:
    _current_job_id.reset(token)


def current_job_id() -> str | None:
    return _current_job_id.get()


def job_log_path(job_id: str, *, settings: Settings | None = None) -> Path:
    resolved_settings = settings or get_settings()
    path = resolved_settings.resolved_log_root / "jobs" / f"{job_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def configure_application_logging(settings: Settings | None = None) -> None:
    global _configured
    if _configured:
        return

    resolved_settings = settings or get_settings()
    root_logger = logging.getLogger()
    level_name = str(resolved_settings.log_level or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s %(levelname)s [%(name)s] [job=%(job_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    context_filter = _JobContextFilter()

    has_file_handler = any(getattr(handler, _CONFIGURED_HANDLER_MARKER, False) for handler in root_logger.handlers)
    if not has_file_handler:
        log_file = resolved_settings.resolved_log_root / "travelmind-api.log"
        file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
        setattr(file_handler, _CONFIGURED_HANDLER_MARKER, True)
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        root_logger.addHandler(file_handler)

    for handler in root_logger.handlers:
        if getattr(handler, _CONFIGURED_HANDLER_MARKER, False):
            handler.addFilter(context_filter)

    _configured = True


def log_job_event(
    event: str,
    *,
    job_id: str | None = None,
    logger_name: str | None = None,
    level: str = "INFO",
    **payload: Any,
) -> Path | None:
    resolved_job_id = job_id or current_job_id()
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "job_id": resolved_job_id,
        "logger": logger_name or "",
        "level": level.upper(),
        "payload": payload,
    }

    settings = get_settings()
    logs_root = settings.resolved_log_root
    global_path = logs_root / "job-events.jsonl"
    global_path.parent.mkdir(parents=True, exist_ok=True)
    per_job_path = job_log_path(resolved_job_id, settings=settings) if resolved_job_id else None

    serialized = json.dumps(record, ensure_ascii=False) + "\n"
    with _jsonl_write_lock:
        global_path.write_text("", encoding="utf-8") if not global_path.exists() else None
        with global_path.open("a", encoding="utf-8") as handle:
            handle.write(serialized)
        if per_job_path is not None:
            with per_job_path.open("a", encoding="utf-8") as handle:
                handle.write(serialized)

    logger = logging.getLogger(logger_name or __name__)
    log_method = getattr(logger, level.lower(), logger.info)
    summary = payload.get("message") or event
    extra = {"job_id": resolved_job_id or "-"}
    log_method(f"{event}: {summary}", extra=extra)
    return per_job_path
