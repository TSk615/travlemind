from __future__ import annotations

import json
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt


def build_responses_payload(chat_payload: dict[str, Any]) -> dict[str, Any]:
    """Translate GrokSearch's chat-completions payload to Responses API input."""
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in chat_payload.get("messages", []):
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user")
        content = message.get("content", "")
        if role == "system":
            instructions.append(str(content))
        else:
            input_items.append({"role": role, "content": content})

    payload: dict[str, Any] = {
        "model": chat_payload["model"],
        "input": input_items,
        "stream": True,
    }
    if instructions:
        payload["instructions"] = "\n\n".join(instructions)
    return payload


def extract_responses_text(payload: dict[str, Any]) -> str:
    output_text = payload.get("output_text")
    if isinstance(output_text, str):
        return output_text

    fragments: list[str] = []
    for output in payload.get("output", []) or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content", []) or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if isinstance(text, str):
                fragments.append(text)
    return "".join(fragments)


class ResponsesGrokSearchProvider:
    """Mixin installed onto upstream GrokSearch when Responses API is selected."""

    async def _execute_stream_with_retry(self, headers: dict, payload: dict, ctx=None) -> str:
        # These helpers live in the upstream package and keep its retry behaviour
        # consistent while only replacing the wire protocol.
        from grok_search.config import config
        from grok_search.logger import log_info
        from grok_search.providers.grok import _WaitWithRetryAfter, _is_retryable_exception

        responses_payload = build_responses_payload(payload)
        timeout = httpx.Timeout(connect=6.0, read=120.0, write=10.0, pool=None)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(config.retry_max_attempts + 1),
                wait=_WaitWithRetryAfter(config.retry_multiplier, config.retry_max_wait),
                retry=retry_if_exception(_is_retryable_exception),
                reraise=True,
            ):
                with attempt:
                    async with client.stream(
                        "POST",
                        f"{self.api_url.rstrip('/')}/responses",
                        headers=headers,
                        json=responses_payload,
                    ) as response:
                        response.raise_for_status()
                        content = await self._parse_responses_stream(response)
                        await log_info(ctx, f"content: {content}", config.debug_enabled)
                        return content

        return ""

    @staticmethod
    async def _parse_responses_stream(response: httpx.Response) -> str:
        fragments: list[str] = []
        completed_payload: dict[str, Any] | None = None

        async for raw_line in response.aiter_lines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("data:"):
                line = line[5:].lstrip()
            if line == "[DONE]":
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue

            if event.get("type") == "response.output_text.delta" and isinstance(event.get("delta"), str):
                fragments.append(event["delta"])
            elif event.get("type") == "response.completed" and isinstance(event.get("response"), dict):
                completed_payload = event["response"]
            elif "output" in event or "output_text" in event:
                completed_payload = event

        if fragments:
            return "".join(fragments)
        return extract_responses_text(completed_payload or {})


def install_responses_provider(server_module: Any) -> None:
    """Replace the provider class captured by grok_search.server at import time."""
    upstream_provider = server_module.GrokSearchProvider
    patched_provider = type(
        "ResponsesGrokSearchProvider",
        (ResponsesGrokSearchProvider, upstream_provider),
        {},
    )
    server_module.GrokSearchProvider = patched_provider
