from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Response

from travelmind_api.api.schemas.llm import LlmProxyRequest
from travelmind_api.services.llm.config import normalize_wire_api

router = APIRouter(prefix="/llm", tags=["llm"])


def _build_endpoint(base_url: str, wire_api: str) -> str:
    base = base_url.strip().rstrip("/")
    mode = normalize_wire_api(wire_api, default="responses")
    if mode == "responses":
        return base if base.endswith("/responses") else f"{base}/responses"
    return base if base.endswith("/chat/completions") else f"{base}/chat/completions"


@router.post("/proxy")
def proxy_llm_request(payload: LlmProxyRequest):
    endpoint = _build_endpoint(payload.base_url, payload.wire_api)
    headers = {
        "Authorization": f"Bearer {payload.api_key}",
        "Content-Type": "application/json",
    }

    try:
        timeout = httpx.Timeout(connect=20.0, read=300.0, write=60.0, pool=60.0)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            upstream = client.post(endpoint, headers=headers, json=payload.payload)
    except httpx.TimeoutException:
        body = json.dumps({"error": {"message": "Upstream model request timed out"}})
        return Response(content=body, status_code=504, media_type="application/json")
    except httpx.HTTPError as exc:
        body = json.dumps({"error": {"message": str(exc)}})
        return Response(content=body, status_code=502, media_type="application/json")

    content_type = upstream.headers.get("content-type", "application/json")
    passthrough_headers = {
        "Content-Type": content_type,
        "Cache-Control": upstream.headers.get("cache-control", "no-cache"),
    }
    trace_id = upstream.headers.get("trace-id")
    if trace_id:
        passthrough_headers["x-upstream-trace-id"] = trace_id

    return Response(content=upstream.text, status_code=upstream.status_code, headers=passthrough_headers)