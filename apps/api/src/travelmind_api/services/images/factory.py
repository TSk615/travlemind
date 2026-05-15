from __future__ import annotations

from travelmind_api.services.images.base import ImageProvider
from travelmind_api.services.images.config import ImageModelConfig
from travelmind_api.services.images.huggingface import HuggingFaceImageProvider
from travelmind_api.services.images.openai_compatible import OpenAICompatibleImageProvider
from travelmind_api.services.images.provider import (
    IMAGE_PROVIDER_A4F,
    IMAGE_PROVIDER_GITEE_AI,
    IMAGE_PROVIDER_HUGGINGFACE,
    IMAGE_PROVIDER_MODELSCOPE,
    IMAGE_PROVIDER_OPENAI_COMPATIBLE,
    normalize_image_provider,
)


def build_image_provider(config: ImageModelConfig) -> ImageProvider:
    provider_name = normalize_image_provider(config.provider, default=IMAGE_PROVIDER_OPENAI_COMPATIBLE)
    if provider_name in {IMAGE_PROVIDER_OPENAI_COMPATIBLE, IMAGE_PROVIDER_A4F, IMAGE_PROVIDER_GITEE_AI, IMAGE_PROVIDER_MODELSCOPE}:
        return OpenAICompatibleImageProvider(config.model_copy(update={"provider": provider_name}))
    if provider_name == IMAGE_PROVIDER_HUGGINGFACE:
        return HuggingFaceImageProvider(config.model_copy(update={"provider": provider_name}))
    raise RuntimeError(f"Unsupported image provider: {provider_name}")
