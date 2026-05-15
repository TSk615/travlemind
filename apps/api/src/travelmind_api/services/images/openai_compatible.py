from __future__ import annotations

import base64
import mimetypes
from typing import Any

import httpx

from travelmind_api.services.images.base import GeneratedImage, ImageProvider, ImageProviderRequest
from travelmind_api.services.images.config import ImageModelConfig


class OpenAICompatibleImageProvider(ImageProvider):
    def __init__(self, config: ImageModelConfig) -> None:
        self._config = config

    def generate(self, request: ImageProviderRequest) -> list[GeneratedImage]:
        with httpx.Client(timeout=self._config.timeout_seconds, follow_redirects=True) as client:
            if request.mode == "image_to_image":
                if not request.source_image_bytes:
                    raise ValueError("source image is required for image_to_image")
                response = client.post(
                    self._config.edit_url,
                    headers={"Authorization": f"Bearer {self._config.api_key}"},
                    data={
                        "model": self._config.model,
                        "prompt": request.prompt,
                        "size": request.size,
                        "response_format": "b64_json",
                        "n": "1",
                    },
                    files={
                        "image": (
                            request.source_image_filename or "source.png",
                            request.source_image_bytes,
                            request.source_image_mime_type or "image/png",
                        )
                    },
                )
            else:
                response = client.post(
                    self._config.generation_url,
                    headers={
                        "Authorization": f"Bearer {self._config.api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._config.model,
                        "prompt": request.prompt,
                        "size": request.size,
                        "response_format": "b64_json",
                        "n": 1,
                    },
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("image provider response root must be an object")
            return self._extract_images(client, payload)

    def _extract_images(self, client: httpx.Client, payload: dict[str, Any]) -> list[GeneratedImage]:
        data = payload.get("data")
        if not isinstance(data, list) or not data:
            raise ValueError("image provider response missing data")

        images: list[GeneratedImage] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            revised_prompt = item.get("revised_prompt")
            encoded = item.get("b64_json")
            if isinstance(encoded, str) and encoded.strip():
                images.append(
                    GeneratedImage(
                        data=base64.b64decode(encoded),
                        mime_type="image/png",
                        revised_prompt=str(revised_prompt) if revised_prompt else None,
                    )
                )
                continue
            url = item.get("url")
            if isinstance(url, str) and url.strip():
                download = client.get(url)
                download.raise_for_status()
                mime_type = download.headers.get("content-type") or mimetypes.guess_type(url)[0] or "image/png"
                images.append(
                    GeneratedImage(
                        data=download.content,
                        mime_type=mime_type,
                        revised_prompt=str(revised_prompt) if revised_prompt else None,
                    )
                )
        if not images:
            raise ValueError("image provider returned no usable images")
        return images
