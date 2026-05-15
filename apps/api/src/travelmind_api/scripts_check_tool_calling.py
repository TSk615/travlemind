from __future__ import annotations

import json
import os
from typing import Any

import httpx

from travelmind_api.core.env import get_env
from travelmind_api.services.llm.config import LlmEndpointConfig


def main() -> int:
    base_url = (get_env("TRAVELMIND_TOOLCHECK_BASE_URL") or get_env("TRAVELMIND_LLM_BASE_URL") or "").strip()
    api_key = (get_env("TRAVELMIND_TOOLCHECK_API_KEY") or get_env("TRAVELMIND_LLM_API_KEY") or "").strip()
    model = (get_env("TRAVELMIND_TOOLCHECK_MODEL") or get_env("TRAVELMIND_LLM_MODEL") or "").strip()
    if not base_url or not api_key or not model:
        print("缺少 TRAVELMIND_TOOLCHECK_BASE_URL / API_KEY / MODEL（或对应的 TRAVELMIND_LLM_*）")
        return 1

    config = LlmEndpointConfig(base_url=base_url.rstrip("/"), api_key=api_key, model=model, wire_api="chat_completions", timeout_seconds=30)

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
    }
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": "请使用 search 工具查询广州今天天气，只返回工具调用，不要直接回答。",
            }
        ],
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "search the web",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query"},
                        },
                        "required": ["query"],
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "temperature": 0.0,
    }

    url = config.endpoint_url
    with httpx.Client(timeout=config.timeout_seconds, follow_redirects=True) as client:
        response = client.post(url, headers=headers, json=payload)

    result: dict[str, Any] = {
        "request_url": url,
        "status_code": response.status_code,
        "content_type": response.headers.get("content-type"),
    }

    try:
        body = response.json()
    except ValueError:
        result["body_preview"] = response.text[:1000]
        result["supports_openai_tool_calling"] = False
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    result["body"] = body
    supports = False
    try:
        choices = body.get("choices") if isinstance(body, dict) else None
        if isinstance(choices, list) and choices:
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
            supports = isinstance(tool_calls, list) and len(tool_calls) > 0
    except Exception:
        supports = False

    result["supports_openai_tool_calling"] = supports
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
