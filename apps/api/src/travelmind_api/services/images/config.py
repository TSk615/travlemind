from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, Field

from travelmind_api.services.images.provider import IMAGE_PROVIDER_OPENAI_COMPATIBLE, ImageProviderName, normalize_image_provider


class ImageModelConfig(BaseModel):
    base_url: str
    api_key: str
    model: str
    provider: ImageProviderName = IMAGE_PROVIDER_OPENAI_COMPATIBLE
    timeout_seconds: float = Field(default=120.0, gt=0)

    @property
    def generation_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/images/generations"):
            return base
        return f"{base}/images/generations"

    @property
    def edit_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/images/edits"):
            return base
        return f"{base}/images/edits"

    @property
    def huggingface_model_url(self) -> str:
        base = self.base_url.rstrip("/")
        if f"/models/{self.model}" in base:
            return base
        if base.endswith("/models"):
            return f"{base}/{self.model}"
        return f"{base}/models/{self.model}"

    @classmethod
    def from_mapping(cls, payload: Mapping[str, object] | None) -> ImageModelConfig | None:
        if payload is None:
            return None
        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        api_key = str(payload.get("api_key") or "").strip()
        model = str(payload.get("model") or "").strip()
        if not base_url or not api_key or not model:
            return None
        timeout_raw = str(payload.get("timeout_seconds") or "120").strip()
        try:
            timeout_seconds = float(timeout_raw)
        except ValueError:
            timeout_seconds = 120.0
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            provider=normalize_image_provider(payload.get("provider")),
            timeout_seconds=timeout_seconds if timeout_seconds > 0 else 120.0,
        )
