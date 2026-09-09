from __future__ import annotations

import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import httpx

from travelmind_api.services.llm import LlmEndpointConfig, OpenAICompatibleClient


@dataclass(frozen=True)
class HelloAgentsInvokeResult:
    content: str
    usage: dict[str, Any]
    latency_ms: int
    citations: list[str] = field(default_factory=list)


class HelloAgentsCompatibleLLM:
    def __init__(
        self,
        config: LlmEndpointConfig,
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        retry_attempts: int = 2,
        rate_limit_retry_attempts: int = 6,
        min_timeout_seconds: float = 120.0,
        stream: bool = False,
        client_factory: Callable[[LlmEndpointConfig], OpenAICompatibleClient] = OpenAICompatibleClient,
    ) -> None:
        effective_timeout = max(float(config.timeout_seconds), float(min_timeout_seconds))
        self._config = config.model_copy(update={"timeout_seconds": effective_timeout})
        self.model = self._config.model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.retry_attempts = max(1, int(retry_attempts))
        self.rate_limit_retry_attempts = max(self.retry_attempts, int(rate_limit_retry_attempts))
        self.stream = bool(stream)
        self.last_citations: list[str] = []
        self.kwargs = {
            "model": self._config.model,
            "api_key": self._config.api_key,
            "base_url": self._config.base_url,
            "temperature": temperature,
            "timeout": int(self._config.timeout_seconds),
            "wire_api": self._config.wire_api,
            "provider_protocol": self._config.provider_protocol,
            "max_tokens": max_tokens,
            "retry_attempts": self.retry_attempts,
            "rate_limit_retry_attempts": self.rate_limit_retry_attempts,
            "min_timeout_seconds": float(min_timeout_seconds),
            "stream": self.stream,
        }
        self._client = client_factory(self._config)

    def invoke(self, messages: list[dict[str, Any]], **kwargs) -> HelloAgentsInvokeResult:
        temperature = float(kwargs.pop("temperature", self.temperature))
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        stream = bool(kwargs.pop("stream", self.stream))
        last_error: Exception | None = None

        for attempt in range(1, max(self.retry_attempts, self.rate_limit_retry_attempts) + 1):
            started = time.perf_counter()
            try:
                request_kwargs: dict[str, Any] = {
                    "messages": deepcopy(messages),
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                if stream:
                    request_kwargs["stream"] = True
                content = self._client.create_chat_completion(**request_kwargs)
                latency_ms = int((time.perf_counter() - started) * 1000)
                citations = [
                    str(item).strip()
                    for item in (getattr(self._client, "last_citations", []) or [])
                    if str(item).strip()
                ]
                self.last_citations = list(dict.fromkeys(citations))
                return HelloAgentsInvokeResult(
                    content=content,
                    usage={},
                    latency_ms=latency_ms,
                    citations=self.last_citations,
                )
            except httpx.HTTPStatusError as exc:
                last_error = exc
                attempt_limit = self.rate_limit_retry_attempts if self._is_rate_limit_http_status(exc) else self.retry_attempts
                if attempt >= attempt_limit or not self._is_retryable_http_status(exc):
                    raise
                time.sleep(min(5.0 * attempt, 12.0))
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    raise
                time.sleep(min(2.0 * attempt, 4.0))
            except httpx.TransportError as exc:
                last_error = exc
                if attempt >= self.retry_attempts:
                    raise
                time.sleep(min(2.0 * attempt, 4.0))
            except ValueError as exc:
                last_error = exc
                attempt_limit = self.rate_limit_retry_attempts if self._is_rate_limit_stream_error(exc) else self.retry_attempts
                if attempt >= attempt_limit or not self._is_retryable_stream_error(exc):
                    raise
                time.sleep(min(5.0 * attempt, 12.0))

        assert last_error is not None
        raise last_error

    @staticmethod
    def _is_retryable_http_status(exc: httpx.HTTPStatusError) -> bool:
        return exc.response.status_code in {408, 429, 500, 502, 503, 504}

    @staticmethod
    def _is_rate_limit_http_status(exc: httpx.HTTPStatusError) -> bool:
        return exc.response.status_code == 429

    @staticmethod
    def _is_retryable_stream_error(exc: ValueError) -> bool:
        message = str(exc).lower()
        if "stream returned an error event" not in message:
            return False
        return any(
            token in message
            for token in (
                "429",
                "rate limit",
                "too many requests",
                "temporarily unavailable",
                "overloaded",
                "quota",
                "503",
                "504",
                "console transport failed",
                "transport request failed",
                "curl:",
                "curl: (92)",
                "http/2 stream",
                "not closed cleanly",
                "internal_error",
                "stream reset",
            )
        )

    @staticmethod
    def _is_rate_limit_stream_error(exc: ValueError) -> bool:
        message = str(exc).lower()
        if "stream returned an error event" not in message:
            return False
        return any(token in message for token in ("429", "rate limit", "too many requests", "quota"))

    def stream_invoke(self, messages: list[dict[str, Any]], **kwargs):
        result = self.invoke(messages, **kwargs)
        yield result.content

    def invoke_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        **kwargs,
    ) -> Any:
        temperature = float(kwargs.pop("temperature", self.temperature))
        max_tokens = kwargs.pop("max_tokens", self.max_tokens)
        return self._client.create_tool_completion(
            messages=deepcopy(messages),
            tools=deepcopy(tools),
            tool_choice=tool_choice,
            temperature=temperature,
            max_tokens=max_tokens,
        )
