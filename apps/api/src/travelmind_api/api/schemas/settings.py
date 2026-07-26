from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class AgentSettingsUpdateRequest(BaseModel):
    provider_protocol: str | None = Field(default=None, max_length=64)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=255)
    wire_api: str | None = Field(default=None, max_length=64)
    agent_provider: str | None = Field(default=None, max_length=64)
    poi_provider_protocol: str | None = Field(default=None, max_length=64)
    poi_base_url: str | None = Field(default=None, max_length=512)
    poi_api_key: str | None = Field(default=None, max_length=2048)
    poi_model: str | None = Field(default=None, max_length=255)
    poi_wire_api: str | None = Field(default=None, max_length=64)

    @model_validator(mode="before")
    @classmethod
    def _coerce_protocol_alias(cls, value: object) -> object:
        if isinstance(value, dict) and "protocol" in value and "provider_protocol" not in value:
            return {**value, "provider_protocol": value["protocol"]}
        return value


class SearchSettingsUpdateRequest(BaseModel):
    provider: str | None = Field(default=None, max_length=64)
    transport: str | None = Field(default=None, max_length=32)
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=2048)
    timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    xhs_source_enabled: bool | None = None


class ImageSettingsUpdateRequest(BaseModel):
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=2048)
    model: str | None = Field(default=None, max_length=255)
    provider: str | None = Field(default=None, max_length=64)


class RuntimeSettingsUpdateRequest(BaseModel):
    agent: AgentSettingsUpdateRequest | None = None
    search: SearchSettingsUpdateRequest | None = None
    image: ImageSettingsUpdateRequest | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_legacy_payload(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        if "agent" in value or "search" in value:
            return value

        agent_keys = {"provider_protocol", "base_url", "api_key", "model", "wire_api", "agent_provider"}
        search_keys = {"provider", "transport", "timeout_seconds", "xhs_source_enabled"}
        image_keys = {"image_base_url", "image_api_key", "image_model", "image_provider"}
        agent_payload = {key: value[key] for key in agent_keys if key in value}
        search_payload = {key: value[key] for key in search_keys if key in value}
        image_payload: dict[str, object] = {}

        if "search_base_url" in value:
            search_payload["base_url"] = value["search_base_url"]
        if "protocol" in value and "provider_protocol" not in agent_payload:
            agent_payload["provider_protocol"] = value["protocol"]
        if "search_api_key" in value:
            search_payload["api_key"] = value["search_api_key"]
        if "search_provider" in value:
            search_payload["provider"] = value["search_provider"]
        if "search_transport" in value:
            search_payload["transport"] = value["search_transport"]
        if "search_timeout_seconds" in value:
            search_payload["timeout_seconds"] = value["search_timeout_seconds"]
        if "image_base_url" in value:
            image_payload["base_url"] = value["image_base_url"]
        if "image_api_key" in value:
            image_payload["api_key"] = value["image_api_key"]
        if "image_model" in value:
            image_payload["model"] = value["image_model"]
        if "image_provider" in value:
            image_payload["provider"] = value["image_provider"]

        normalized: dict[str, object] = {}
        if agent_payload:
            normalized["agent"] = agent_payload
        if search_payload:
            normalized["search"] = search_payload
        if image_payload:
            normalized["image"] = image_payload
        return normalized or value


class AgentSettingsResponse(BaseModel):
    provider_protocol: str = "openai"
    base_url: str | None = None
    api_key_masked: str | None = None
    has_api_key: bool = False
    model: str | None = None
    wire_api: str | None = None
    agent_provider: str = "standard"
    configured: bool = False
    poi_provider_protocol: str = "openai"
    poi_base_url: str | None = None
    poi_api_key_masked: str | None = None
    poi_has_api_key: bool = False
    poi_model: str | None = None
    poi_wire_api: str | None = None
    poi_configured: bool = False


class SearchSettingsResponse(BaseModel):
    provider: str = "groksearch"
    transport: str = "mcp"
    base_url: str | None = None
    api_key_masked: str | None = None
    has_api_key: bool = False
    timeout_seconds: float = 30.0
    xhs_source_enabled: bool = False
    configured: bool = False


class ImageSettingsResponse(BaseModel):
    base_url: str | None = None
    api_key_masked: str | None = None
    has_api_key: bool = False
    model: str | None = None
    provider: str = "openai_compatible"
    configured: bool = False


class RuntimeSettingsResponse(BaseModel):
    agent: AgentSettingsResponse
    search: SearchSettingsResponse
    image: ImageSettingsResponse
