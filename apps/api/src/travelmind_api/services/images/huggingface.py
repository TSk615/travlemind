from __future__ import annotations

import base64
from typing import Any

import httpx

from travelmind_api.services.images.base import GeneratedImage, ImageProvider, ImageProviderRequest
from travelmind_api.services.images.config import ImageModelConfig


def _parse_size(size: str) -> tuple[int, int]:
    parts = str(size or "").lower().split("x", 1)
    if len(parts) != 2:
        return (1024, 1024)
    try:
        width = int(parts[0])
        height = int(parts[1])
    except ValueError:
        return (1024, 1024)
    return (max(width, 64), max(height, 64))


class HuggingFaceImageProvider(ImageProvider):
    def __init__(self, config: ImageModelConfig) -> None:
        self._config = config

    def generate(self, request: ImageProviderRequest) -> list[GeneratedImage]:
        width, height = _parse_size(request.size)
        headers = {
            "Authorization": f"Bearer {self._config.api_key}",
        }

        if request.mode == "image_to_image":
            if not request.source_image_bytes:
                raise ValueError("source image is required for image_to_image")
            payload = {
                "inputs": base64.b64encode(request.source_image_bytes).decode("ascii"),
                "parameters": {
                    "prompt": request.prompt,
                    "negative_prompt": request.negative_prompt or "",
                    "target_size": {"width": width, "height": height},
                },
            }
            headers["Content-Type"] = "application/json"
            with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=True) as client:
                response = client.post(self._config.huggingface_model_url, headers=headers, json=payload)
                response.raise_for_status()
                mime_type = response.headers.get("content-type") or "image/png"
                return [GeneratedImage(data=response.content, mime_type=mime_type)]

        payload = {
            "inputs": request.prompt,
            "parameters": {
                "negative_prompt": request.negative_prompt or "",
                "width": width,
                "height": height,
            },
        }
        headers["Content-Type"] = "application/json"
        with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=True) as client:
            response = client.post(self._config.huggingface_model_url, headers=headers, json=payload)
            response.raise_for_status()
            mime_type = response.headers.get("content-type") or "image/png"
            return [GeneratedImage(data=response.content, mime_type=mime_type)]
