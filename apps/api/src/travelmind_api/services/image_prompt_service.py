from __future__ import annotations

import json
import re
from dataclasses import dataclass

from travelmind_api.services.llm import LlmConfig, OpenAICompatibleClient


@dataclass(frozen=True)
class ImagePromptComposePayload:
    title: str
    destination: str
    scene_prompt: str
    prompt: str
    negative_prompt: str
    style_tags: list[str]
    reference_urls: list[str]
    reference_count: int = 0


@dataclass(frozen=True)
class ImagePromptComposeResult:
    title: str
    optimized_prompt: str
    negative_prompt: str


def _normalize_tags(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = str(value or "").strip()
        if not candidate:
            continue
        key = candidate.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized


def _fallback_compose(payload: ImagePromptComposePayload) -> ImagePromptComposeResult:
    tags = _normalize_tags(payload.style_tags)
    title = payload.title.strip() or "旅行灵感图"
    if payload.destination.strip():
        title = payload.title.strip() or f"{payload.destination.strip()} 旅行灵感图"
    prompt_parts = [
        payload.destination.strip(),
        payload.scene_prompt.strip(),
        payload.prompt.strip(),
        ", ".join(tags) if tags else "",
        "travel atmosphere, detailed composition, natural lighting, high aesthetic quality",
    ]
    optimized_prompt = ", ".join(part for part in prompt_parts if part)
    negative_prompt = payload.negative_prompt.strip() or "low quality, blurry, distorted face, duplicated subject, watermark, text"
    return ImagePromptComposeResult(
        title=title,
        optimized_prompt=optimized_prompt,
        negative_prompt=negative_prompt,
    )


def _extract_json_object(raw_text: str) -> dict[str, object] | None:
    raw_text = raw_text.strip()
    if not raw_text:
        return None
    try:
        parsed = json.loads(raw_text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None


def compose_image_prompt(payload: ImagePromptComposePayload, llm_config: LlmConfig | None) -> ImagePromptComposeResult:
    fallback = _fallback_compose(payload)
    if llm_config is None:
        return fallback

    system_prompt = (
        "You rewrite travel image prompts for image generation. "
        "Return one JSON object only with keys title, optimized_prompt, negative_prompt. "
        "All user-visible text must be in Simplified Chinese."
    )
    user_prompt = json.dumps(
        {
            "title": payload.title,
            "destination": payload.destination,
            "scene_prompt": payload.scene_prompt,
            "prompt": payload.prompt,
            "negative_prompt": payload.negative_prompt,
            "style_tags": _normalize_tags(payload.style_tags),
            "reference_urls": payload.reference_urls[:6],
            "reference_count": payload.reference_count,
        },
        ensure_ascii=False,
    )

    try:
        client = OpenAICompatibleClient(llm_config)
        raw = client.create_chat_completion(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.4,
            max_tokens=400,
        )
        parsed = _extract_json_object(raw)
        if not parsed:
            return fallback
        title = str(parsed.get("title") or fallback.title).strip() or fallback.title
        optimized_prompt = str(parsed.get("optimized_prompt") or fallback.optimized_prompt).strip() or fallback.optimized_prompt
        negative_prompt = str(parsed.get("negative_prompt") or fallback.negative_prompt).strip() or fallback.negative_prompt
        return ImagePromptComposeResult(
            title=title,
            optimized_prompt=optimized_prompt,
            negative_prompt=negative_prompt,
        )
    except Exception:
        return fallback
