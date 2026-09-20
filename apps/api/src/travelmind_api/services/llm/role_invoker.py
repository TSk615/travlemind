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
        }


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
        messages = [
            {"role": "system", "content": invocation.system_prompt},
            {
                "role": "user",
                "content": json.dumps(dict(invocation.input_payload), ensure_ascii=False),
            },
        ]
        started = time.perf_counter()
        content = client.create_chat_completion(
            messages=messages,
            temperature=invocation.temperature,
            max_tokens=invocation.max_tokens,
            stream=invocation.stream,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        citations = [
            str(item).strip()
            for item in (getattr(client, "last_citations", []) or [])
            if str(item).strip()
        ]
        return RoleInvocationResult(
            request_id=generate_identifier("llmreq"),
            role_name=invocation.role_name,
            content=content,
            model=invocation.endpoint.model,
            provider_protocol=invocation.endpoint.provider_protocol,
            wire_api=invocation.endpoint.wire_api,
            endpoint_host=urlparse(invocation.endpoint.base_url).netloc or invocation.endpoint.base_url,
            prompt_version=invocation.prompt_version,
            latency_ms=latency_ms,
            citations=list(dict.fromkeys(citations)),
            usage=None,
        )

