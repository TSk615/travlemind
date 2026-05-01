from __future__ import annotations

from typing import Literal

IMAGE_PROVIDER_OPENAI_COMPATIBLE = "openai_compatible"
IMAGE_PROVIDER_HUGGINGFACE = "huggingface"
IMAGE_PROVIDER_GITEE_AI = "gitee_ai"
IMAGE_PROVIDER_MODELSCOPE = "modelscope"
IMAGE_PROVIDER_A4F = "a4f"

ImageProviderName = Literal["openai_compatible", "huggingface", "gitee_ai", "modelscope", "a4f"]


def normalize_image_provider(value: object | None, *, default: ImageProviderName = IMAGE_PROVIDER_OPENAI_COMPATIBLE) -> ImageProviderName:
    candidate = str(value or "").strip().lower()
    if candidate in {"openai_compatible", "openai-compatible", "openai", ""}:
        return IMAGE_PROVIDER_OPENAI_COMPATIBLE
    if candidate in {"huggingface", "hf", "hugging_face"}:
        return IMAGE_PROVIDER_HUGGINGFACE
    if candidate in {"gitee_ai", "gitee-ai", "gitee"}:
        return IMAGE_PROVIDER_GITEE_AI
    if candidate in {"modelscope", "model_scope"}:
        return IMAGE_PROVIDER_MODELSCOPE
    if candidate in {"a4f"}:
        return IMAGE_PROVIDER_A4F
    return default


def is_supported_image_provider(value: object | None) -> bool:
    candidate = str(value or "").strip().lower()
    return candidate in {
        "openai_compatible",
        "openai-compatible",
        "openai",
        "huggingface",
        "hf",
        "hugging_face",
        "gitee_ai",
        "gitee-ai",
        "gitee",
        "modelscope",
        "model_scope",
        "a4f",
    }
