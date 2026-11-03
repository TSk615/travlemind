from __future__ import annotations

import json
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from travelmind_api.core.security import generate_identifier
from travelmind_api.services.llm.client import OpenAICompatibleClient
from travelmind_api.services.llm.config import LlmEndpointConfig


@dataclass(frozen=True)
class RoleInvocation:
    role_name: str
    prompt_version: str
    system_prompt: str
    input_payload: Mapping[str, Any]
    endpoint: LlmEndpointConfig
    temperature: float = 0.2
    max_tokens: int | None = None
    stream: bool = False
    max_request_attempts: int = 2


@dataclass(frozen=True)
class RoleInvocationResult:
    request_id: str
    role_name: str
    content: str
    model: str
    provider_protocol: str
    wire_api: str
    endpoint_host: str
    prompt_version: str
    latency_ms: int
    citations: list[str] = field(default_factory=list)
    # None means the endpoint did not return usage metadata. It must not be
    # converted to zero because that would under-report cost.
    usage: dict[str, Any] | None = None
    retry_count: int = 0
    cache_reused: bool = False
    request_count: int = 0

    def checkpoint_metadata(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "role_name": self.role_name,
            "model": self.model,
            "provider_protocol": self.provider_protocol,
            "wire_api": self.wire_api,
            "endpoint_host": self.endpoint_host,
            "prompt_version": self.prompt_version,
            "latency_ms": self.latency_ms,
            "citations": list(self.citations),
            "usage": self.usage,
            "retry_count": self.retry_count,
            "cache_reused": self.cache_reused,
            "request_count": self.request_count,
        }


_FAILURE_METADATA_ATTRIBUTE = "_travelmind_role_invocation_failure_metadata"


def get_role_invocation_failure_metadata(exc: BaseException) -> dict[str, Any]:
    """Return sanitized telemetry attached to an upstream invocation failure."""

    value = getattr(exc, _FAILURE_METADATA_ATTRIBUTE, None)
    return dict(value) if isinstance(value, Mapping) else {}


class RoleInvoker(Protocol):
    def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
        ...


class OpenAICompatibleRoleInvoker:
    """Invoke a workflow role through the existing multi-protocol client."""

    def __init__(
        self,
        *,
        client_factory: Callable[[LlmEndpointConfig], OpenAICompatibleClient] = OpenAICompatibleClient,
    ) -> None:
        self._client_factory = client_factory

    def invoke(self, invocation: RoleInvocation) -> RoleInvocationResult:
        client = self._client_factory(invocation.endpoint)
        # Only the final planner is constrained; research/tool conversations keep
        # their existing protocols. Unsupported protocols are not modified.
        client.json_object_mode = (invocation.role_name == "itinerary_planner"
                                   and str(invocation.endpoint.provider_protocol).lower() in {"openai", "newapi"})
        input_payload = dict(invocation.input_payload)
        client.structured_output_schema = None
        if client.json_object_mode:
            from travelmind_api.services.planner_output_schema import full_plan_schema
            client.structured_output_schema = input_payload.get("structured_output_schema") or full_plan_schema()
            # Replace the old hand-written sample (which can drift from runtime
            # models). Slot repairs keep their own narrowly authorized schema.
            input_payload["output_schema"] = client.structured_output_schema
        client.request_attempt_limit = max(int(invocation.max_request_attempts), 1)
        client.request_deadline_seconds = float(invocation.endpoint.timeout_seconds)
        request_id = generate_identifier("llmreq")
        messages = [
            {"role": "system", "content": invocation.system_prompt + ("\n只输出一个完整的 JSON 对象，不输出 Markdown 或额外解释。" if client.json_object_mode else "")},
            {
                "role": "user",
                "content": json.dumps(input_payload, ensure_ascii=False),
            },
        ]
        started = time.perf_counter()
        try:
            content = client.create_chat_completion(
                messages=messages,
                temperature=invocation.temperature,
                max_tokens=invocation.max_tokens,
                stream=invocation.stream,
            )
        except Exception as exc:
            metadata = {
                "request_id": request_id,
                "role_name": invocation.role_name,
                "model": invocation.endpoint.model,
                "provider_protocol": invocation.endpoint.provider_protocol,
                "wire_api": invocation.endpoint.wire_api,
                "endpoint_host": urlparse(invocation.endpoint.base_url).netloc or invocation.endpoint.base_url,
                "prompt_version": invocation.prompt_version,
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "citations": [
                    str(item).strip()
                    for item in (getattr(client, "last_citations", []) or [])
                    if str(item).strip()
                ],
                "usage": (
                    dict(getattr(client, "last_usage"))
                    if isinstance(getattr(client, "last_usage", None), dict)
                    else None
                ),
                "retry_count": int(getattr(client, "last_retry_count", 0) or 0),
                "request_count": int(getattr(client, "last_request_count", 0) or 0),
                "cache_reused": False,
            }
            try:
                setattr(exc, _FAILURE_METADATA_ATTRIBUTE, metadata)
            except Exception:
                # Preserve the original exception even for unusual immutable
                # exception implementations; retry classification depends on it.
                pass
            raise
        latency_ms = int((time.perf_counter() - started) * 1000)
        citations = [
            str(item).strip()
            for item in (getattr(client, "last_citations", []) or [])
            if str(item).strip()
        ]
        return RoleInvocationResult(
            request_id=request_id,
            role_name=invocation.role_name,
            content=content,
            model=invocation.endpoint.model,
            provider_protocol=invocation.endpoint.provider_protocol,
            wire_api=invocation.endpoint.wire_api,
            endpoint_host=urlparse(invocation.endpoint.base_url).netloc or invocation.endpoint.base_url,
            prompt_version=invocation.prompt_version,
            latency_ms=latency_ms,
            citations=list(dict.fromkeys(citations)),
            usage=(
                dict(getattr(client, "last_usage"))
                if isinstance(getattr(client, "last_usage", None), dict)
                else None
            ),
            retry_count=int(getattr(client, "last_retry_count", 0) or 0),
            request_count=int(getattr(client, "last_request_count", 0) or 0),
        )
