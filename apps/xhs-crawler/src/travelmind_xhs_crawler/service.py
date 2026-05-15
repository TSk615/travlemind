from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings
from .schemas import InternalXhsBindingState, InternalXhsSessionSearchRequest, XhsSearchPost, XhsSearchResponse

_LOGGER = logging.getLogger(__name__)


class OpenCliRunnerError(RuntimeError):
    pass


class XhsSessionExpiredError(OpenCliRunnerError):
    pass


@dataclass
class _BindingRecord:
    user_id: str
    state: InternalXhsBindingState


class SubprocessOpenCliAdapter:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._data_root = Path(settings.data_root)
        self._data_root.mkdir(parents=True, exist_ok=True)

    def health(self) -> dict[str, Any]:
        node_error: str | None = None
        try:
            node_version = self._run_text_command([self._settings.node_binary, "--version"], timeout_seconds=10)
        except OpenCliRunnerError as exc:
            node_version = ""
            node_error = str(exc)
        node_major = _parse_node_major(node_version) if node_version else None
        opencli_path = shutil.which(self._settings.opencli_binary) or self._settings.opencli_binary
        return {
            "data_root": str(self._data_root),
            "node_binary": self._settings.node_binary,
            "node_version": node_version,
            "node_error": node_error,
            "node_major": node_major,
            "node_version_ok": node_major is not None and node_major >= self._settings.node_min_major,
            "opencli_binary": self._settings.opencli_binary,
            "opencli_path": opencli_path,
            "opencli_exists": bool(shutil.which(self._settings.opencli_binary) or Path(self._settings.opencli_binary).exists()),
            "bind_start_command": self._settings.xhs_bind_start_command,
            "bind_poll_command": self._settings.xhs_bind_poll_command,
            "search_command": self._settings.xhs_search_command,
            "note_command": self._settings.xhs_note_command,
        }

    def start_binding(self, *, bind_id: str, user_id: str) -> InternalXhsBindingState:
        payload = self._run_json_command(
            self._settings.xhs_bind_start_command,
            extra_env={
                "TRAVELMIND_XHS_BIND_ID": bind_id,
                "TRAVELMIND_XHS_USER_ID": user_id,
            },
        )
        return self._binding_state_from_payload(payload, bind_id=bind_id, default_status="pending")

    def poll_binding(self, *, bind_id: str) -> InternalXhsBindingState:
        payload = self._run_json_command(
            self._settings.xhs_bind_poll_command,
            extra_env={"TRAVELMIND_XHS_BIND_ID": bind_id},
        )
        return self._binding_state_from_payload(payload, bind_id=bind_id, default_status="pending")

    def search(self, *, user_id: str, destination: str, queries: list[str], limit_per_query: int, session_payload: dict[str, Any]) -> list[dict[str, Any]]:
        if not isinstance(session_payload, dict) or not session_payload:
            raise XhsSessionExpiredError("Missing Xiaohongshu session payload")

        run_dir = self._data_root / "runs" / f"run-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=True)
        session_file = run_dir / "session.json"
        session_file.write_text(json.dumps(session_payload, ensure_ascii=False), encoding="utf-8")

        records: list[dict[str, Any]] = []
        for query in queries:
            payload = self._run_json_command(
                self._settings.xhs_search_command,
                extra_env={
                    "TRAVELMIND_XHS_USER_ID": user_id,
                    "TRAVELMIND_XHS_DESTINATION": destination,
                    "TRAVELMIND_XHS_QUERY": query,
                    "TRAVELMIND_XHS_LIMIT_PER_QUERY": str(limit_per_query),
                    "TRAVELMIND_XHS_SESSION_FILE": str(session_file),
                    "TRAVELMIND_XHS_RUN_DIR": str(run_dir),
                },
            )
            records.extend(_extract_items(payload))
        return records

    def fetch_note_detail(self, *, user_id: str, note_ref: str, destination: str, session_payload: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(session_payload, dict) or not session_payload:
            raise XhsSessionExpiredError("Missing Xiaohongshu session payload")

        run_dir = self._data_root / "notes" / f"note-{uuid.uuid4().hex}"
        run_dir.mkdir(parents=True, exist_ok=True)
        session_file = run_dir / "session.json"
        session_file.write_text(json.dumps(session_payload, ensure_ascii=False), encoding="utf-8")

        payload = self._run_json_command(
            self._settings.xhs_note_command,
            extra_env={
                "TRAVELMIND_XHS_USER_ID": user_id,
                "TRAVELMIND_XHS_DESTINATION": destination,
                "TRAVELMIND_XHS_NOTE_REF": note_ref,
                "TRAVELMIND_XHS_SESSION_FILE": str(session_file),
                "TRAVELMIND_XHS_RUN_DIR": str(run_dir),
            },
        )
        if isinstance(payload, dict):
            return payload
        items = _extract_items(payload)
        return items[0] if items else None

    def delete_session(self, *, user_id: str) -> None:
        del user_id

    def _binding_state_from_payload(self, payload: Any, *, bind_id: str, default_status: str) -> InternalXhsBindingState:
        if not isinstance(payload, dict):
            raise OpenCliRunnerError("Binding command must return a JSON object")
        normalized = dict(payload)
        normalized["bind_id"] = str(normalized.get("bind_id") or bind_id)
        normalized["status"] = str(normalized.get("status") or default_status)
        return InternalXhsBindingState.model_validate(normalized)

    def _run_text_command(self, command: list[str], *, timeout_seconds: int) -> str:
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(timeout_seconds, 1),
                check=False,
            )
        except FileNotFoundError as exc:
            raise OpenCliRunnerError(f"Command not found: {command[0]}") from exc
        if completed.returncode != 0:
            raise OpenCliRunnerError((completed.stderr or completed.stdout or "Command failed").strip())
        return (completed.stdout or "").strip()

    def _run_json_command(self, command: list[str], *, extra_env: dict[str, str] | None = None) -> Any:
        env = {**os.environ, **(extra_env or {})}
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(self._settings.opencli_timeout_seconds, 1),
                check=False,
                env=env,
            )
        except FileNotFoundError as exc:
            raise OpenCliRunnerError(f"Command not found: {command[0]}") from exc

        raw = (completed.stdout or completed.stderr or "").strip()
        payload: Any = None
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None

        if completed.returncode != 0:
            detail = _extract_error_message(payload, raw)
            code = payload.get("code") if isinstance(payload, dict) else None
            if code == "xhs_session_expired":
                raise XhsSessionExpiredError(detail)
            raise OpenCliRunnerError(detail)

        if payload is None:
            raise OpenCliRunnerError(f"Command returned non-JSON output: {raw[:300]}")
        if isinstance(payload, dict) and payload.get("code") == "xhs_session_expired":
            raise XhsSessionExpiredError(str(payload.get("message") or "XHS session expired"))
        return payload


class XhsBrowserNodeService:
    def __init__(self, settings: Settings, *, adapter: SubprocessOpenCliAdapter | None = None) -> None:
        self._settings = settings
        self._adapter = adapter or SubprocessOpenCliAdapter(settings)
        self._bindings: dict[str, _BindingRecord] = {}
        self._lock = threading.Lock()

    def health(self) -> dict[str, Any]:
        return self._adapter.health()

    def start_binding(self, *, user_id: str) -> InternalXhsBindingState:
        bind_id = f"xhb_{uuid.uuid4().hex}"
        state = self._adapter.start_binding(bind_id=bind_id, user_id=user_id)
        with self._lock:
            self._bindings[bind_id] = _BindingRecord(user_id=user_id, state=state)
        return state

    def get_binding(self, *, bind_id: str) -> InternalXhsBindingState:
        cached = self._bindings.get(bind_id)
        state = cached.state if cached is not None else None
        if state is None or state.status not in {"authorized", "expired", "cancelled", "failed"}:
            latest = self._adapter.poll_binding(bind_id=bind_id)
            if state is not None:
                latest = latest.model_copy(
                    update={
                        "verification_url": latest.verification_url or state.verification_url,
                        "verification_code": latest.verification_code or state.verification_code,
                        "qr_image_data_url": latest.qr_image_data_url or state.qr_image_data_url,
                    }
                )
            with self._lock:
                self._bindings[bind_id] = _BindingRecord(user_id=cached.user_id if cached is not None else "", state=latest)
            return latest
        return state

    def search_session(self, payload: InternalXhsSessionSearchRequest) -> XhsSearchResponse:
        result = self._build_search_result(payload, include_debug=False)
        raw_posts = result.get("posts")
        if not isinstance(raw_posts, list):
            return XhsSearchResponse(posts=[])
        posts = [XhsSearchPost.model_validate(item) for item in raw_posts if isinstance(item, dict)]
        return XhsSearchResponse(posts=posts)

    def search_session_debug(self, payload: InternalXhsSessionSearchRequest) -> dict[str, Any]:
        return self._build_search_result(payload, include_debug=True)

    def _build_search_result(self, payload: InternalXhsSessionSearchRequest, *, include_debug: bool) -> dict[str, Any]:
        normalized_queries = _normalize_queries(payload.queries)
        if not normalized_queries:
            return {
                "destination": payload.destination,
                "queries": [],
                "limit_per_query": payload.limit_per_query,
                "record_count": 0,
                "post_count": 0,
                "posts": [],
                "records": [],
            }
        search_records = self._adapter.search(
            user_id=payload.user_id,
            destination=payload.destination,
            queries=normalized_queries,
            limit_per_query=payload.limit_per_query,
            session_payload=payload.session_payload,
        )

        posts: list[XhsSearchPost] = []
        debug_records: list[dict[str, Any]] = [] if include_debug else []
        seen: set[str] = set()
        for index, record in enumerate(search_records):
            raw_record = dict(record)
            merged = dict(record)
            note_ref = _extract_note_reference(raw_record)
            detail_applied = False
            detail_error: str | None = None
            if note_ref:
                try:
                    detail = self._adapter.fetch_note_detail(
                        user_id=payload.user_id,
                        note_ref=note_ref,
                        destination=payload.destination,
                        session_payload=payload.session_payload,
                    )
                except OpenCliRunnerError as exc:
                    _LOGGER.warning("XHS note fetch failed for %s: %s", note_ref, exc)
                    detail_error = str(exc)
                else:
                    if isinstance(detail, dict):
                        merged.update(detail)
                        detail_applied = True
            post = _to_post(merged, payload.destination)
            included_in_posts = False
            dedupe_reason: str | None = None
            if post is None:
                dedupe_reason = "unparseable"
            else:
                dedupe_key = post.post_id.strip() or post.url.strip().lower()
                if dedupe_key in seen or post.url.strip().lower() in seen:
                    dedupe_reason = "duplicate"
                else:
                    seen.add(dedupe_key)
                    seen.add(post.url.strip().lower())
                    posts.append(post)
                    included_in_posts = True
            if include_debug:
                debug_records.append(
                    {
                        "record_index": index,
                        "note_ref": note_ref,
                        "detail_applied": detail_applied,
                        "detail_error": detail_error,
                        "included_in_posts": included_in_posts,
                        "dedupe_reason": dedupe_reason,
                        "record_summary": _build_debug_record_summary(raw_record, merged),
                        "raw_image_fields": _collect_debug_image_fields(raw_record),
                        "merged_image_fields": _collect_debug_image_fields(merged),
                        "raw_image_candidates": _collect_debug_image_candidates(raw_record),
                        "merged_image_candidates": _collect_debug_image_candidates(merged),
                        "parsed_post": post.model_dump(mode="json") if post is not None else None,
                    }
                )
        return {
            "destination": payload.destination,
            "queries": normalized_queries,
            "limit_per_query": payload.limit_per_query,
            "record_count": len(search_records),
            "post_count": len(posts),
            "posts": [post.model_dump(mode="json") for post in posts],
            "records": debug_records if include_debug else [],
        }

    def delete_session(self, *, user_id: str) -> None:
        self._adapter.delete_session(user_id=user_id)
        with self._lock:
            self._bindings = {key: value for key, value in self._bindings.items() if value.user_id != user_id}


def _normalize_queries(queries: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for query in queries:
        candidate = str(query or "").strip()
        key = candidate.casefold()
        if not candidate or key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("items", "results", "data", "notes", "posts"):
        candidate = payload.get(key)
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]
    return [payload]


def _extract_note_reference(record: dict[str, Any]) -> str | None:
    for key in ("post_id", "note_id", "id", "noteId", "url", "note_url", "share_url"):
        value = _coerce_text(record.get(key))
        if value:
            return value
    return None


def _to_post(record: dict[str, Any], destination: str) -> XhsSearchPost | None:
    post_id = _first_text(record, "post_id", "note_id", "id", "noteId")
    url = _first_text(record, "url", "note_url", "share_url", "note_link")
    if not url and post_id:
        url = f"https://www.xiaohongshu.com/explore/{post_id}"
    title = _first_text(record, "title", "note_title", "name") or ""
    excerpt = _first_text(record, "excerpt", "desc", "content", "note_desc") or ""
    if not url or (not title and not excerpt):
        return None
    author = (
        _first_text(record, "author", "nickname", "user_name")
        or _nested_text(record, ("user", "nickname"))
        or _nested_text(record, ("user", "name"))
        or ""
    )
    return XhsSearchPost(
        post_id=post_id or url.rsplit("/", 1)[-1],
        title=title,
        url=url,
        author=author,
        published_at=_normalize_time(_first_text(record, "published_at", "publish_time", "time", "create_time", "last_update_time")),
        excerpt=_trim(excerpt, 400),
        engagement_hint=_build_engagement_hint(record),
        tags=_collect_tags(record),
        image_urls=_collect_image_urls(record),
        raw_destination_hint=_first_text(record, "raw_destination_hint", "ip_location", "location") or destination,
    )


def _first_text(payload: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        text = _coerce_text(payload.get(key))
        if text:
            return text
    return None


def _nested_text(payload: dict[str, Any], path: tuple[str, ...]) -> str | None:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return _coerce_text(current)


def _coerce_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        candidate = " ".join(value.split()).strip()
        return candidate or None
    if isinstance(value, (int, float)):
        return str(value)
    return None


def _collect_tags(payload: dict[str, Any]) -> list[str]:
    raw = payload.get("tags") or payload.get("tag_list") or payload.get("topics") or []
    tags: list[str] = []
    seen: set[str] = set()
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                candidate = _coerce_text(item.get("name") or item.get("tag") or item.get("text"))
            else:
                candidate = _coerce_text(item)
            if not candidate:
                continue
            key = candidate.casefold()
            if key in seen:
                continue
            seen.add(key)
            tags.append(candidate)
    return tags[:8]


def _build_engagement_hint(payload: dict[str, Any]) -> str | None:
    metrics = []
    for label, key in (("likes", "liked_count"), ("collects", "collected_count"), ("comments", "comment_count"), ("shares", "share_count")):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            metrics.append(f"{label}: {int(value)}")
        elif isinstance(value, str) and value.strip().isdigit():
            metrics.append(f"{label}: {value.strip()}")
    if metrics:
        return ", ".join(metrics)
    return _coerce_text(payload.get("engagement_hint"))


def _collect_image_urls(payload: dict[str, Any]) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()

    def record(value: Any) -> None:
        text = _coerce_text(value)
        if not text:
            return
        candidate = text.strip()
        lowered = candidate.casefold()
        if not lowered.startswith("http") or lowered in seen:
            return
        if not any(ext in lowered for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")) and "image" not in lowered and "pic" not in lowered:
            return
        seen.add(lowered)
        urls.append(candidate)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                normalized_key = str(key).casefold()
                if normalized_key in {
                    "url",
                    "image",
                    "image_url",
                    "imageurl",
                    "origin_image_url",
                    "originurl",
                    "display_url",
                    "master_url",
                    "thumbnail",
                    "thumbnail_url",
                    "cover",
                    "cover_url",
                    "image_list",
                    "images",
                    "note_image_list",
                    "photo",
                    "photo_url",
                }:
                    if isinstance(item, list):
                        for entry in item:
                            visit(entry)
                    else:
                        record(item)
                visit(item)
            return
        if isinstance(node, list):
            for item in node:
                visit(item)

    visit(payload)
    return urls[:6]


_DEBUG_IMAGE_URL_PATTERN = re.compile(r"https?://[^,\s\"'<>]+", re.IGNORECASE)


def _collect_debug_image_candidates(payload: Any) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def record(value: str) -> None:
        candidate = value.strip()
        lowered = candidate.casefold()
        if not candidate.startswith("http") or lowered in seen:
            return
        if not any(ext in lowered for ext in (".jpg", ".jpeg", ".png", ".webp", ".gif")) and "image" not in lowered and "pic" not in lowered:
            return
        seen.add(lowered)
        candidates.append(candidate)

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                visit(value)
            return
        if isinstance(node, list):
            for item in node:
                visit(item)
            return
        if isinstance(node, str):
            for match in _DEBUG_IMAGE_URL_PATTERN.findall(node):
                record(match)

    visit(payload)
    return candidates[:12]


def _collect_debug_image_fields(payload: Any) -> list[dict[str, Any]]:
    fields: list[dict[str, Any]] = []

    def visit(node: Any, path: str = "") -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                key_text = str(key)
                current_path = f"{path}.{key_text}" if path else key_text
                normalized_key = key_text.casefold()
                if any(marker in normalized_key for marker in ("image", "cover", "photo", "thumbnail", "pic")):
                    fields.append({"path": current_path, "value": _preview_debug_value(value)})
                if isinstance(value, (dict, list)):
                    visit(value, current_path)
            return
        if isinstance(node, list):
            for index, item in enumerate(node[:6]):
                visit(item, f"{path}[{index}]")

    visit(payload)
    return fields[:24]


def _build_debug_record_summary(raw_record: dict[str, Any], merged_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "post_id": _first_text(merged_record, "post_id", "note_id", "id", "noteId"),
        "title": _first_text(merged_record, "title", "note_title", "name"),
        "url": _first_text(merged_record, "url", "note_url", "share_url", "note_link"),
        "author": _first_text(merged_record, "author", "nickname", "user_name") or _nested_text(merged_record, ("user", "nickname")),
        "note_type": _first_text(raw_record, "type"),
        "raw_excerpt": _trim(_first_text(raw_record, "desc", "content", "note_desc") or "", 160) or None,
        "merged_excerpt": _trim(_first_text(merged_record, "desc", "content", "note_desc") or "", 160) or None,
    }


def _preview_debug_value(value: Any) -> Any:
    if isinstance(value, str):
        return _trim(value, 400)
    if isinstance(value, list):
        return [_preview_debug_value(item) for item in value[:6]]
    if isinstance(value, dict):
        preview: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 8:
                preview["..."] = f"+{len(value) - 8} more keys"
                break
            preview[str(key)] = _preview_debug_value(item)
        return preview
    return value


def _normalize_time(value: str | None) -> str | None:
    if not value:
        return None
    candidate = value.strip()
    if candidate.isdigit():
        timestamp = int(candidate)
        if timestamp > 10_000_000_000:
            timestamp //= 1000
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError:
        return value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _trim(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return f"{text[: max(limit - 1, 1)].rstrip()}..."


def _extract_error_message(payload: Any, raw: str) -> str:
    if isinstance(payload, dict):
        return str(payload.get("message") or payload.get("error") or raw[:300] or "OpenCLI command failed")
    return raw[:300] or "OpenCLI command failed"


def _parse_node_major(raw: str) -> int | None:
    candidate = raw.strip().lstrip("v")
    if not candidate:
        return None
    major = candidate.split(".", 1)[0]
    return int(major) if major.isdigit() else None
