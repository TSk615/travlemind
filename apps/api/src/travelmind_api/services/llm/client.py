from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import httpx

from travelmind_api.services.llm.config import LlmEndpointConfig


class OpenAICompatibleClient:
    def __init__(self, config: LlmEndpointConfig, *, http_client: httpx.Client | None = None) -> None:
        self._config = config
        self._http_client = http_client

    def create_chat_completion(
        self,
        *,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        if self._config.wire_api == "responses":
            standard_payload = self._build_text_payload(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                wire_api="responses",
                stream=False,
            )
            try:
                body = self._post_json(self._config, standard_payload)
            except httpx.HTTPStatusError as exc:
                status_code = exc.response.status_code if exc.response is not None else None
                if status_code != 400:
                    raise
                streaming_payload = self._build_text_payload(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    wire_api="responses",
                    stream=True,
                )
                body = self._post_responses_streaming_with_eof_retry(streaming_payload)
            try:
                return self._extract_responses_content(body)
            except ValueError as exc:
                if "did not contain text output" not in str(exc):
                    raise
                fallback_config = self._config.model_copy(update={"wire_api": "chat_completions"})
                fallback_body = self._post_json(
                    fallback_config,
                    self._build_text_payload(messages=messages, temperature=temperature, max_tokens=max_tokens, wire_api="chat_completions"),
                )
                return self._extract_chat_completions_content(fallback_body)

        body = self._post_json(
            self._config,
            self._build_text_payload(messages=messages, temperature=temperature, max_tokens=max_tokens, wire_api=self._config.wire_api),
        )
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
        # hello_agents Function Calling flow expects an OpenAI Chat Completions-style response
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
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        return payload

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
        try:
            return self._post_json(self._config, payload)
        except httpx.TransportError as exc:
            if not self._is_retryable_stream_eof_error(exc):
                raise
            return self._post_json(self._config, payload)

    def _post_json(self, config: LlmEndpointConfig, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        }
        if self._http_client is not None:
            response = self._http_client.post(config.endpoint_url, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=config.timeout_seconds, follow_redirects=True) as client:
                response = client.post(config.endpoint_url, headers=headers, json=payload)

        response.raise_for_status()
        content_type = (response.headers.get("content-type") or "").lower()
        if config.wire_api == "responses" and ("text/event-stream" in content_type or response.text.lstrip().startswith(("event:", "data:"))):
            return {"output_text": self._extract_responses_text_from_sse(response.text)}
        try:
            body = response.json()
        except ValueError as exc:
            preview = response.text[:400] if hasattr(response, "text") else ""
            raise ValueError(f"Upstream LLM response was not valid JSON: {preview or '<empty body>'}") from exc
        if not isinstance(body, dict):
            raise ValueError("Upstream LLM response root must be an object")
        return body

    def _is_retryable_stream_eof_error(self, exc: httpx.TransportError) -> bool:
        message = str(exc).strip().lower()
        if "eof" not in message:
            return False
        return any(token in message for token in ("ssl", "protocol", "unexpected_eof", "unexpected eof"))

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

    def _extract_responses_text_from_sse(self, stream_text: str) -> str:
        data_lines = [
            line[6:]
            for line in stream_text.splitlines()
            if line.startswith("data: ")
        ]

        combined = ""
        completed_text: str | None = None
        for line in data_lines:
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
