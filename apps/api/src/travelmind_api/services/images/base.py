from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class ImageProviderRequest:
    mode: str
    prompt: str
    negative_prompt: str | None = None
    source_image_bytes: bytes | None = None
    source_image_filename: str | None = None
    source_image_mime_type: str | None = None
    reference_image_urls: list[str] = field(default_factory=list)
    size: str = "1024x1024"


@dataclass(frozen=True)
class GeneratedImage:
    data: bytes
    mime_type: str = "image/png"
    revised_prompt: str | None = None


class ImageProvider(Protocol):
    def generate(self, request: ImageProviderRequest) -> list[GeneratedImage]:
        ...
