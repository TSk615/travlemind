from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import httpx

from travelmind_api.services.llm.config import LlmEndpointConfig, normalize_provider_protocol

logger = logging.getLogger(__name__)

# Only these upstream statuses are treated as transient and worth retrying.
# 400 (and other 4xx) means the request itself is wrong: retrying cannot help.
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
# Timeout-ish statuses where retrying the same buffered (non-stream) request
# will likely time out again; the remedy is escalating to a streaming request.
_STREAM_ESCALATION_STATUS_CODES = frozenset({408, 504})
_MAX_RETRY_ATTEMPTS = 2
_BACKOFF_BASE_SECONDS = 1.0
_MAX_RETRY_AFTER_SECONDS = 30.0


class LlmRequestBudgetExceeded(RuntimeError):
    """Raised before a request would exceed one role invocation's HTTP budget."""


class LlmRequestDeadlineExceeded(TimeoutError):
    """Raised when one role invocation exhausts its shared wall-clock budget."""


class OpenAICompatibleClient:
    def __init__(self, config: LlmEndpointConfig, *, http_client: httpx.Client | None = None) -> None:
        self._config = config
        self._http_client = http_client
        # Search-capable gateways may return citations alongside assistant text.
        # Keep the metadata available to callers without changing the long-standing
        # create_chat_completion() string return type.
        self.json_object_mode = False
        self.last_citations: list[str] = []
        self.last_usage: dict[str, Any] | None = None
        self.last_retry_count = 0
        self.last_request_count = 0
        self.request_attempt_limit = _MAX_RETRY_ATTEMPTS + 1
        self.request_deadline_seconds = float(config.timeout_seconds)
        self._deadline_at: float | None = None
        self._monotonic: Callable[[], float] = time.monotonic
        # Injection point so tests can avoid real waiting during retry backoff.
        self._sleep: Callable[[float], None] = time.sleep

    def create_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> str:
        self._begin_invocation()
        protocol = normalize_provider_protocol(self._config.provider_protocol)
        stream = bool(stream or self._requires_streaming())
        if protocol == "gemini":
            return self._create_gemini_completion(messages=messages, temperature=temperature, max_tokens=max_tokens)
        if protocol == "claude":
            return self._create_claude_completion(messages=messages, temperature=temperature, max_tokens=max_tokens)
        return self._create_openai_compatible_completion(messages=messages, temperature=temperature, max_tokens=max_tokens, stream=stream)

    def _begin_invocation(self) -> None:
        self.last_citations = []
        self.last_usage = None
        self.last_retry_count = 0
        self.last_request_count = 0
        self._deadline_at = self._monotonic() + max(float(self.request_deadline_seconds), 0.001)

    def _requires_streaming(self) -> bool:
        model = str(getattr(self._config, "model", "") or "").strip().lower()
        base_url = str(getattr(self._config, "base_url", "") or "").strip().lower()
        return "grok" in model or "x.ai" in base_url

    def _create_openai_compatible_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
        stream: bool,
    ) -> str:
        if self._config.wire_api == "responses":
            standard_payload = self._build_text_payload(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                wire_api="responses",
                stream=stream,
            )
            try:
                body = (
                    self._post_streaming_with_eof_retry(self._config, standard_payload)
                    if stream
                    else self._post_json(self._config, standard_payload, escalate_statuses=_STREAM_ESCALATION_STATUS_CODES)
                )
            except httpx.HTTPStatusError as exc:
                if stream or not self._should_escalate_to_streaming(exc):
                    raise
                streaming_payload = self._build_text_payload(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    wire_api="responses",
                    stream=True,
                )
                body = self._post_streaming_with_eof_retry(self._config, streaming_payload)
            try:
                self.last_citations = self._extract_citation_urls(body)
                return self._extract_responses_content(body)
            except ValueError as exc:
                if "did not contain text output" not in str(exc):
                    raise
                fallback_config = self._config.model_copy(update={"wire_api": "chat_completions"})
                fallback_payload = self._build_text_payload(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    wire_api="chat_completions",
                    stream=True if stream else None,
                )
                fallback_body = self._post_json(
                    fallback_config,
                    fallback_payload,
                ) if not stream else self._post_streaming_with_eof_retry(fallback_config, fallback_payload)
                self.last_citations = self._extract_citation_urls(fallback_body)
                return self._extract_chat_completions_content(fallback_body)

        chat_payload = self._build_text_payload(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            wire_api=self._config.wire_api,
            stream=True if stream else None,
        )
        body = self._post_json(
            self._config,
            chat_payload,
        ) if not stream else self._post_streaming_with_eof_retry(self._config, chat_payload)
        self.last_citations = self._extract_citation_urls(body)
        return self._extract_chat_completions_content(body)

    def create_tool_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        tool_choice: str | dict[str, Any] = "auto",
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> Any:
        self._begin_invocation()
        protocol = normalize_provider_protocol(self._config.provider_protocol)
        if protocol not in {"openai", "newapi", "neiapi"}:
            raise ValueError(f"Tool calling is not implemented for {protocol} protocol")
        # Some OpenAI-compatible function-calling gateways expect a Chat Completions-style response.
        # with choices[0].message.tool_calls, so tool-enabled roles force the compatible path.
        chat_config = self._config.model_copy(update={"wire_api": "chat_completions"})
        payload = {
            "model": chat_config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        body = self._post_json(chat_config, payload)
        return self._to_namespace(body)

    def _create_gemini_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        payload = self._build_gemini_payload(messages=messages, temperature=temperature, max_tokens=max_tokens)
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._config.api_key,
        }
        body = self._post_json_to_url(self._config.endpoint_url, headers, payload)
        return self._extract_gemini_content(body)

    def _create_claude_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
    ) -> str:
        payload = self._build_claude_payload(messages=messages, temperature=temperature, max_tokens=max_tokens)
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
            "x-api-key": self._config.api_key,
        }
        body = self._post_json_to_url(self._config.endpoint_url, headers, payload)
        return self._extract_claude_content(body)

    def _build_text_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
        wire_api: str,
        stream: bool | None = None,
    ) -> dict[str, Any]:
        if wire_api == "responses":
            payload: dict[str, Any] = {
                "model": self._config.model,
                "input": [
                    {
                        "role": message.get("role", "user"),
                        "content": self._normalize_message_content_for_responses(message.get("content")),
                    }
                    for message in messages
                ],
                "temperature": temperature,
            }
            if stream is not None:
                payload["stream"] = stream
            if max_tokens is not None:
                payload["max_output_tokens"] = max_tokens
            if self.json_object_mode:
                payload["text"] = {"format": {"type": "json_object"}}
            return payload

        payload = {
            "model": self._config.model,
            "messages": [
                {
                    **message,
                    "content": self._normalize_message_content_for_chat(message.get("content")),
                }
                for message in messages
            ],
            "temperature": temperature,
        }
        if self.json_object_mode:
            payload["response_format"] = {"type": "json_object"}
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if stream is not None:
            payload["stream"] = stream
        return payload

    def _build_gemini_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        system_parts: list[dict[str, str]] = []
        contents: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user").strip().lower()
            parts = self._normalize_message_content_for_gemini(message.get("content"))
            if role == "system":
                system_parts.extend(parts)
                continue
            contents.append(
                {
                    "role": "model" if role == "assistant" else "user",
                    "parts": parts,
                }
            )

        payload: dict[str, Any] = {
            "contents": contents or [{"role": "user", "parts": [{"text": ""}]}],
            "generationConfig": {"temperature": temperature},
        }
        if system_parts:
            payload["systemInstruction"] = {"parts": system_parts}
        if max_tokens is not None:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        return payload

    def _build_claude_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int | None,
    ) -> dict[str, Any]:
        system_text: list[str] = []
        normalized_messages: list[dict[str, Any]] = []
        for message in messages:
            role = str(message.get("role") or "user").strip().lower()
            text = "\n".join(self._extract_text_parts_for_plain_provider(message.get("content")))
            if role == "system":
                if text.strip():
                    system_text.append(text.strip())
                continue
            next_role = "assistant" if role == "assistant" else "user"
            content = [{"type": "text", "text": text}]
            if normalized_messages and normalized_messages[-1]["role"] == next_role:
                normalized_messages[-1]["content"].extend(content)
            else:
                normalized_messages.append({"role": next_role, "content": content})

        payload: dict[str, Any] = {
            "model": self._config.model,
            "max_tokens": max_tokens or 2048,
            "messages": normalized_messages or [{"role": "user", "content": [{"type": "text", "text": ""}]}],
            "temperature": temperature,
        }
        if system_text:
            payload["system"] = "\n\n".join(system_text)
        return payload

    def _normalize_message_content_for_gemini(self, content: Any) -> list[dict[str, str]]:
        parts = [{"text": text} for text in self._extract_text_parts_for_plain_provider(content) if text.strip()]
        return parts or [{"text": ""}]

    def _extract_text_parts_for_plain_provider(self, content: Any) -> list[str]:
        if isinstance(content, str):
            return [content]
        blocks = content if isinstance(content, list) else [content]
        text_parts: list[str] = []
        for block in blocks:
            if not isinstance(block, dict):
                text = str(block or "").strip()
                if text:
                    text_parts.append(text)
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type in {"text", "input_text", "output_text"}:
                text = str(block.get("text") or block.get("content") or "").strip()
                if text:
                    text_parts.append(text)
                continue
            if block_type in {"image_url", "input_image"}:
                image_url = self._extract_image_url(block.get("image_url"))
                if image_url:
                    text_parts.append(f"[Image: {image_url}]")
                continue
            text = str(block.get("text") or block.get("content") or "").strip()
            if text:
                text_parts.append(text)
        return text_parts or [""]

    def _normalize_message_content_for_responses(self, content: Any) -> list[dict[str, Any]]:
        if isinstance(content, str):
            return [{"type": "input_text", "text": content}]
        blocks = content if isinstance(content, list) else [content]
        normalized: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                text = str(block or "").strip()
                if text:
                    normalized.append({"type": "input_text", "text": text})
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type == "input_text":
                text = str(block.get("text") or "").strip()
                if text:
                    normalized.append({"type": "input_text", "text": text})
                continue
            if block_type == "text":
                text = str(block.get("text") or block.get("content") or "").strip()
                if text:
                    normalized.append({"type": "input_text", "text": text})
                continue
            if block_type == "input_image":
                image_url = self._extract_image_url(block.get("image_url"))
                if image_url:
                    normalized.append({"type": "input_image", "image_url": image_url})
                continue
            if block_type == "image_url":
                image_url = self._extract_image_url(block.get("image_url"))
                if image_url:
                    normalized.append({"type": "input_image", "image_url": image_url})
                continue
            text = str(block.get("text") or block.get("content") or "").strip()
            if text:
                normalized.append({"type": "input_text", "text": text})
        return normalized or [{"type": "input_text", "text": ""}]

    def _normalize_message_content_for_chat(self, content: Any) -> Any:
        if isinstance(content, str):
            return content
        blocks = content if isinstance(content, list) else [content]
        normalized: list[dict[str, Any]] = []
        for block in blocks:
            if not isinstance(block, dict):
                text = str(block or "").strip()
                if text:
                    normalized.append({"type": "text", "text": text})
                continue
            block_type = str(block.get("type") or "").strip()
            if block_type in {"text", "input_text"}:
                text = str(block.get("text") or block.get("content") or "").strip()
                if text:
                    normalized.append({"type": "text", "text": text})
                continue
            if block_type in {"image_url", "input_image"}:
                image_url = self._extract_image_url(block.get("image_url"))
                if image_url:
                    normalized.append({"type": "image_url", "image_url": {"url": image_url}})
                continue
            text = str(block.get("text") or block.get("content") or "").strip()
            if text:
                normalized.append({"type": "text", "text": text})
        return normalized or ""

    def _extract_image_url(self, value: Any) -> str | None:
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        if isinstance(value, dict):
            normalized = str(value.get("url") or "").strip()
            return normalized or None
        return None

    def _post_responses_streaming_with_eof_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post_streaming_with_eof_retry(self._config, payload)

    def _post_streaming_with_eof_retry(self, config: LlmEndpointConfig, payload: dict[str, Any]) -> dict[str, Any]:
        # Historical name kept for compatibility. The bounded retry inside
        # _post_json now covers stream EOF and other transport errors as well
        # as retryable HTTP status codes.
        return self._post_json(config, payload)

    def _post_json(
        self,
        config: LlmEndpointConfig,
        payload: dict[str, Any],
        *,
        escalate_statuses: frozenset[int] = frozenset(),
    ) -> dict[str, Any]:
        return self._request_with_retry(
            lambda: self._post_json_once(config, payload), escalate_statuses=escalate_statuses
        )

    def _should_escalate_to_streaming(self, exc: httpx.HTTPStatusError) -> bool:
        status_code = exc.response.status_code if exc.response is not None else None
        if status_code in _STREAM_ESCALATION_STATUS_CODES:
            return True
        if status_code == 400 and exc.response is not None:
            # Some upstreams (e.g. rainflow-style gateways) reject buffered
            # requests with a 400 that explicitly asks for stream=true.
            try:
                body_text = exc.response.text or ""
            except Exception:  # pragma: no cover - defensive
                body_text = ""
            return "stream" in body_text.lower()
        return False

    def _request_with_retry(
        self,
        send: Callable[[], dict[str, Any]],
        *,
        escalate_statuses: frozenset[int] = frozenset(),
    ) -> dict[str, Any]:
        attempt = 0
        while True:
            self._remaining_request_timeout(self._config)
            if self.last_request_count >= max(int(self.request_attempt_limit), 1):
                raise LlmRequestBudgetExceeded(
                    f"LLM request budget exhausted after {self.last_request_count} attempt(s)"
                )
            self.last_request_count += 1
            if attempt > 0:
                # Count only retry requests that are actually sent. A retry that
                # is rejected by the per-role budget is not an upstream call.
                self.last_retry_count += 1
            try:
                result = send()
                # A synchronous transport may only return after its timeout.
                # Do not let an over-deadline response continue the workflow.
                self._remaining_request_timeout(self._config)
                return result
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code in escalate_statuses:
                    # The caller has a better remedy (switch to streaming) than
                    # retrying the same request in place.
                    raise
                if attempt >= _MAX_RETRY_ATTEMPTS or status_code not in RETRYABLE_STATUS_CODES:
                    raise
                delay = self._retry_delay_seconds(attempt, exc.response)
            except httpx.TransportError as exc:
                if attempt >= _MAX_RETRY_ATTEMPTS:
                    raise
                # Stream EOF errors have historically been retried immediately;
                # keep the first retry instant for them, back off afterwards.
                if attempt == 0 and self._is_retryable_stream_eof_error(exc):
                    delay = 0.0
                else:
                    delay = self._retry_delay_seconds(attempt, None)
            attempt += 1
            if self.last_request_count >= max(int(self.request_attempt_limit), 1):
                raise LlmRequestBudgetExceeded(
                    f"LLM request budget exhausted after {self.last_request_count} attempt(s)"
                )
            if delay > 0:
                if delay >= self._remaining_request_timeout(self._config):
                    raise LlmRequestDeadlineExceeded("LLM role deadline would be exceeded by retry backoff")
                self._sleep(delay)

    def _remaining_request_timeout(self, config: LlmEndpointConfig) -> float:
        configured = max(float(config.timeout_seconds), 0.001)
        if self._deadline_at is None:
            return configured
        remaining = self._deadline_at - self._monotonic()
        if remaining <= 0:
            raise LlmRequestDeadlineExceeded("LLM role deadline exhausted")
        return min(configured, remaining)

    def _retry_delay_seconds(self, attempt: int, response: httpx.Response | None) -> float:
        if response is not None and response.status_code == 429:
            retry_after = str(response.headers.get("Retry-After") or "").strip()
            if retry_after:
                try:
                    parsed = float(retry_after)
                except ValueError:
                    pass
                else:
                    if parsed >= 0:
                        return min(parsed, _MAX_RETRY_AFTER_SECONDS)
        return _BACKOFF_BASE_SECONDS * (2**attempt)

    def _post_json_once(self, config: LlmEndpointConfig, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        if payload.get("stream") is True:
            return self._post_sse_once(config, headers, payload)
        request_timeout = self._remaining_request_timeout(config)
        if self._http_client is not None:
            response = self._http_client.post(
                config.endpoint_url, headers=headers, json=payload, timeout=request_timeout
            )
        else:
            with httpx.Client(timeout=request_timeout, follow_redirects=True) as client:
                response = client.post(config.endpoint_url, headers=headers, json=payload)
        return self._parse_post_response(config, response)

    def _post_sse_once(self, config: LlmEndpointConfig, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        request_timeout = self._remaining_request_timeout(config)
        if self._http_client is not None:
            stream_ctx = self._http_client.stream(
                "POST", config.endpoint_url, headers=headers, json=payload, timeout=request_timeout
            )
            return self._consume_sse_response(config, stream_ctx)
        with httpx.Client(timeout=request_timeout, follow_redirects=True) as client:
            stream_ctx = client.stream("POST", config.endpoint_url, headers=headers, json=payload)
            return self._consume_sse_response(config, stream_ctx)

    def _consume_sse_response(self, config: LlmEndpointConfig, stream_ctx: Any) -> dict[str, Any]:
        # Read the SSE body incrementally so the read timeout applies to each
        # chunk instead of buffering the whole (potentially slow) response.
        with stream_ctx as response:
            content_type = (response.headers.get("content-type") or "").lower()
            if response.status_code >= 400 or "text/event-stream" not in content_type:
                response.read()
                return self._parse_post_response(config, response)
            lines: list[str] = []
            for line in response.iter_lines():
                self._remaining_request_timeout(config)
                lines.append(line)
            return self._parse_sse_body(config, "\n".join(lines))

    def _parse_post_response(self, config: LlmEndpointConfig, response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:1200].strip()
            # Keep upstream validation details in the job log, but never echo
            # authorization headers or the request payload.
            if detail:
                raise httpx.HTTPStatusError(f"{exc}; upstream={detail}", request=exc.request, response=exc.response) from exc
            raise
        content_type = (response.headers.get("content-type") or "").lower()
        is_event_stream = "text/event-stream" in content_type or response.text.lstrip().startswith(("event:", "data:"))
        if is_event_stream:
            return self._parse_sse_body(config, response.text)
        try:
            body = response.json()
        except ValueError as exc:
            preview = response.text[:400] if hasattr(response, "text") else ""
            raise ValueError(f"Upstream LLM response was not valid JSON: {preview or '<empty body>'}") from exc
        if not isinstance(body, dict):
            raise ValueError("Upstream LLM response root must be an object")
        self._log_usage(self._find_usage(body))
        return body

    def _parse_sse_body(self, config: LlmEndpointConfig, stream_text: str) -> dict[str, Any]:
        self._log_usage(self._find_usage_in_sse(stream_text))
        citations: list[str] = []
        for line in self._iter_sse_data_lines(stream_text):
            if not line or line == "[DONE]":
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            citations.extend(self._extract_citation_urls(parsed))
        citations = list(dict.fromkeys(citations))
        citation_metadata = {"_citations": citations} if citations else {}
        if config.wire_api == "responses":
            return {"output_text": self._extract_responses_text_from_sse(stream_text), **citation_metadata}
        return {"choices": [{"message": {"content": self._extract_chat_completions_text_from_sse(stream_text)}}], **citation_metadata}

    def _extract_citation_urls(self, value: Any) -> list[str]:
        """Extract URLs from citation/search metadata without scraping assistant prose."""
        citation_keys = {
            "citation",
            "citations",
            "annotation",
            "annotations",
            "source",
            "sources",
            "source_url",
            "source_urls",
            "references",
            "reference",
            "web_results",
            "search_results",
            "_citations",
        }
        url_keys = {"url", "uri", "href", "link", "source_url", "source_urls"}
        found: list[str] = []

        def add(candidate: Any) -> None:
            if isinstance(candidate, str):
                normalized = candidate.strip()
                if normalized.startswith(("https://", "http://")):
                    found.append(normalized)

        def visit(node: Any, citation_context: bool = False) -> None:
            if isinstance(node, dict):
                for raw_key, child in node.items():
                    key = str(raw_key).strip().casefold().replace("-", "_")
                    child_context = citation_context or key in citation_keys or "citation" in key
                    if child_context and key in url_keys:
                        if isinstance(child, list):
                            for item in child:
                                add(item)
                        else:
                            add(child)
                    visit(child, child_context)
            elif isinstance(node, list):
                for child in node:
                    visit(child, citation_context)
            elif citation_context:
                add(node)

        visit(value)
        return list(dict.fromkeys(found))

    def _post_json_to_url(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_with_retry(lambda: self._post_json_to_url_once(url, headers, payload))

    def _post_json_to_url_once(self, url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        request_timeout = self._remaining_request_timeout(self._config)
        if self._http_client is not None:
            response = self._http_client.post(url, headers=headers, json=payload, timeout=request_timeout)
        else:
            with httpx.Client(timeout=request_timeout, follow_redirects=True) as client:
                response = client.post(url, headers=headers, json=payload)

        response.raise_for_status()
        try:
            body = response.json()
        except ValueError as exc:
            preview = response.text[:400] if hasattr(response, "text") else ""
            raise ValueError(f"Upstream LLM response was not valid JSON: {preview or '<empty body>'}") from exc
        if not isinstance(body, dict):
            raise ValueError("Upstream LLM response root must be an object")
        self._log_usage(self._find_usage(body))
        return body

    def _find_usage(self, body: dict[str, Any]) -> dict[str, Any] | None:
        for key in ("usage", "usageMetadata"):
            usage = body.get(key)
            if isinstance(usage, dict):
                return usage
        nested = body.get("response")
        if isinstance(nested, dict):
            usage = nested.get("usage")
            if isinstance(usage, dict):
                return usage
        return None

    def _find_usage_in_sse(self, stream_text: str) -> dict[str, Any] | None:
        usage: dict[str, Any] | None = None
        for line in self._iter_sse_data_lines(stream_text):
            if not line or line == "[DONE]":
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                found = self._find_usage(parsed)
                if found is not None:
                    usage = found
        return usage

    def _log_usage(self, usage: dict[str, Any] | None) -> None:
        if not isinstance(usage, dict):
            return
        prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", usage.get("promptTokenCount")))
        completion_tokens = usage.get("completion_tokens", usage.get("output_tokens", usage.get("candidatesTokenCount")))
        total_tokens = usage.get("total_tokens", usage.get("totalTokenCount"))
        normalized: dict[str, int | float] = {}
        for key, value in (
            ("prompt_tokens", prompt_tokens),
            ("completion_tokens", completion_tokens),
            ("total_tokens", total_tokens),
        ):
            if isinstance(value, bool):
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            normalized[key] = int(numeric) if numeric.is_integer() else numeric
        if "total_tokens" not in normalized and {
            "prompt_tokens",
            "completion_tokens",
        }.issubset(normalized):
            normalized["total_tokens"] = normalized["prompt_tokens"] + normalized["completion_tokens"]
        if normalized:
            previous = self.last_usage or {}
            combined = dict(previous)
            for key, value in normalized.items():
                combined[key] = previous.get(key, 0) + value
            self.last_usage = combined
        if prompt_tokens is None and completion_tokens is None:
            return
        logger.info(
            "llm usage: model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s",
            self._config.model,
            prompt_tokens,
            completion_tokens,
            total_tokens,
        )

    def _is_retryable_stream_eof_error(self, exc: httpx.TransportError) -> bool:
        message = str(exc).strip().lower()
        if "eof" in message:
            return any(token in message for token in ("ssl", "protocol", "unexpected_eof", "unexpected eof"))
        return any(
            token in message
            for token in (
                "curl: (92)",
                "http/2 stream",
                "not closed cleanly",
                "internal_error",
                "stream reset",
            )
        )

    def _extract_chat_completions_content(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("OpenAI-compatible response missing choices")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(message, dict):
            raise ValueError("OpenAI-compatible response missing message payload")

        content = message.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    text_parts.append(block["text"])
            if text_parts:
                return "\n".join(text_parts)
        raise ValueError("OpenAI-compatible response content was empty")

    def _extract_chat_completions_text_from_sse(self, stream_text: str) -> str:
        combined = ""
        reasoning_combined = ""
        completed_text: str | None = None
        diagnostics: list[str] = []
        for line in self._iter_sse_data_lines(stream_text):
            if not line or line == "[DONE]":
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            if isinstance(parsed.get("error"), dict):
                error = parsed["error"]
                message = error.get("message") or error.get("code") or error
                raise ValueError(f"Chat Completions stream returned an error event: {message}")

            choices = parsed.get("choices")
            if isinstance(choices, list):
                for choice in choices:
                    if not isinstance(choice, dict):
                        continue
                    finish_reason = choice.get("finish_reason")
                    delta = choice.get("delta")
                    if isinstance(delta, dict):
                        diagnostics.append(self._summarize_chat_stream_choice(choice, delta))
                        combined += self._extract_text_from_chat_content(delta.get("content"))
                        for key in ("text", "output_text"):
                            text = delta.get(key)
                            if isinstance(text, str):
                                combined += text
                        reasoning = delta.get("reasoning_content")
                        if isinstance(reasoning, str):
                            reasoning_combined += reasoning
                    else:
                        diagnostics.append(self._summarize_chat_stream_choice(choice, None))
                    message = choice.get("message")
                    if isinstance(message, dict):
                        text = self._extract_text_from_chat_content(message.get("content"))
                        if text.strip():
                            completed_text = text
                    text = choice.get("text")
                    if isinstance(text, str):
                        combined += text
                    if finish_reason is not None and len(diagnostics) < 8:
                        diagnostics.append(f"finish_reason={finish_reason}")
                continue

            for key in ("content", "text", "output_text"):
                text = parsed.get(key)
                if isinstance(text, str):
                    combined += text

        final_text = completed_text or combined or reasoning_combined
        if final_text.strip():
            return final_text
        diagnostic_suffix = f"; observed events: {' | '.join(diagnostics[:8])}" if diagnostics else ""
        raise ValueError(f"Chat Completions stream did not contain assistant text{diagnostic_suffix}")

    def _summarize_chat_stream_choice(self, choice: dict[str, Any], delta: dict[str, Any] | None) -> str:
        choice_keys = ",".join(sorted(str(key) for key in choice.keys()))
        if delta is None:
            return f"choice_keys={choice_keys}; delta=missing"
        delta_keys = ",".join(sorted(str(key) for key in delta.keys()))
        return f"choice_keys={choice_keys}; delta_keys={delta_keys or 'none'}"

    def _extract_text_from_chat_content(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            text = content.get("text") or content.get("content") or content.get("output_text")
            return text if isinstance(text, str) else ""
        if isinstance(content, list):
            text_parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text") or block.get("content") or block.get("output_text")
                    if isinstance(text, str):
                        text_parts.append(text)
            return "".join(text_parts)
        return ""

    def _extract_gemini_content(self, payload: dict[str, Any]) -> str:
        candidates = payload.get("candidates")
        if isinstance(candidates, list):
            text_parts: list[str] = []
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content")
                if not isinstance(content, dict):
                    continue
                parts = content.get("parts")
                if not isinstance(parts, list):
                    continue
                for part in parts:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        text_parts.append(part["text"])
            if text_parts:
                return "\n".join(text_parts)

        text = payload.get("text") or payload.get("output_text")
        if isinstance(text, str) and text.strip():
            return text
        raise ValueError("Gemini response did not contain assistant text")

    def _extract_claude_content(self, payload: dict[str, Any]) -> str:
        content = payload.get("content")
        if isinstance(content, list):
            text_parts = [
                str(block.get("text"))
                for block in content
                if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
            ]
            if text_parts:
                return "\n".join(text_parts)

        text = payload.get("output_text")
        if isinstance(text, str) and text.strip():
            return text
        raise ValueError("Claude response did not contain assistant text")

    def _extract_responses_text_from_sse(self, stream_text: str) -> str:
        combined = ""
        completed_text: str | None = None
        for line in self._iter_sse_data_lines(stream_text):
            if not line or line == "[DONE]":
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = parsed.get("type")
            if event_type == "response.output_text.delta" and isinstance(parsed.get("delta"), str):
                combined += parsed["delta"]
            elif event_type == "response.output_text.done" and isinstance(parsed.get("text"), str):
                completed_text = parsed["text"]
            elif event_type == "response.completed":
                output = parsed.get("response", {}).get("output")
                if isinstance(output, list):
                    text_parts: list[str] = []
                    for item in output:
                        if not isinstance(item, dict):
                            continue
                        content = item.get("content")
                        if not isinstance(content, list):
                            continue
                        for block in content:
                            if not isinstance(block, dict):
                                continue
                            text = block.get("text")
                            if isinstance(text, str) and text.strip():
                                text_parts.append(text)
                    if text_parts:
                        completed_text = "\n".join(text_parts)

        final_text = completed_text or combined
        if final_text.strip():
            return final_text
        raise ValueError("Responses API stream did not contain assistant text")

    def _iter_sse_data_lines(self, stream_text: str) -> list[str]:
        data_lines: list[str] = []
        for raw_line in stream_text.splitlines():
            line = raw_line.strip()
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
        return data_lines

    def _extract_responses_content(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output = payload.get("output")
        if isinstance(output, list):
            text_parts = self._extract_text_parts_from_responses_output(output)
            if text_parts:
                return "\n".join(text_parts)

        nested_response = payload.get("response")
        if isinstance(nested_response, dict):
            nested_output_text = nested_response.get("output_text")
            if isinstance(nested_output_text, str) and nested_output_text.strip():
                return nested_output_text
            nested_output = nested_response.get("output")
            if isinstance(nested_output, list):
                text_parts = self._extract_text_parts_from_responses_output(nested_output)
                if text_parts:
                    return "\n".join(text_parts)

        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            try:
                return self._extract_chat_completions_content(payload)
            except ValueError:
                pass

        raise ValueError("Responses API payload did not contain text output")

    def _extract_text_parts_from_responses_output(self, output: list[Any]) -> list[str]:
        text_parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if isinstance(content, str) and content.strip():
                text_parts.append(content)
                continue
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text)
                    continue
                if block.get("type") in {"output_text", "text"} and isinstance(block.get("content"), str) and block["content"].strip():
                    text_parts.append(block["content"])
        return text_parts

    def _to_namespace(self, value: Any) -> Any:
        if isinstance(value, dict):
            return SimpleNamespace(**{key: self._to_namespace(item) for key, item in value.items()})
        if isinstance(value, list):
            return [self._to_namespace(item) for item in value]
        return value
