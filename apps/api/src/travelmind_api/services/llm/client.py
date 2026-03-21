from __future__ import annotations

from typing import Any

import httpx

from travelmind_api.services.llm.config import LlmConfig


class OpenAICompatibleClient:
    def __init__(self, config: LlmConfig, *, http_client: httpx.Client | None = None) -> None:
        self._config = config
        self._http_client = http_client

    def create_chat_completion(self, *, messages: list[dict[str, Any]], temperature: float = 0.2) -> str:
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
            "Content-Type": "application/json",
        }

        if self._config.wire_api == "responses":
            payload = {
                "model": self._config.model,
                "input": [
                    {
                        "role": message.get("role", "user"),
                        "content": [
                            {
                                "type": "input_text",
                                "text": str(message.get("content") or "")
                            }
                        ]
                    }
                    for message in messages
                ],
                "temperature": temperature,
            }
        else:
            payload = {
                "model": self._config.model,
                "messages": messages,
                "temperature": temperature,
            }

        if self._http_client is not None:
            response = self._http_client.post(self._config.endpoint_url, headers=headers, json=payload)
        else:
            with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=True) as client:
                response = client.post(self._config.endpoint_url, headers=headers, json=payload)

        response.raise_for_status()
        body = response.json()
        if self._config.wire_api == "responses":
            return self._extract_responses_content(body)
        return self._extract_chat_completions_content(body)

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

    def _extract_responses_content(self, payload: dict[str, Any]) -> str:
        output_text = payload.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        output = payload.get("output")
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
                    if isinstance(block.get("text"), str) and block["text"].strip():
                        text_parts.append(block["text"])
            if text_parts:
                return "\n".join(text_parts)

        raise ValueError("Responses API payload did not contain text output")