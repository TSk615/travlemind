from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolParameter:
    name: str
    type: str
    description: str = ""
    required: bool = False
    default: Any = None


@dataclass(frozen=True)
class ToolResponse:
    ok: bool
    text: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def success(cls, *, text: str, data: dict[str, Any] | None = None) -> "ToolResponse":
        return cls(ok=True, text=text, data=dict(data or {}))

    @classmethod
    def error(cls, *, code: str, message: str) -> "ToolResponse":
        return cls(ok=False, error_code=code, error_message=message)


class Tool:
    """Minimal framework-neutral contract for executable remote tools."""

    def __init__(self, *, name: str, description: str) -> None:
        self.name = name
        self.description = description

    def get_parameters(self) -> list[ToolParameter]:
        raise NotImplementedError

    def run(self, parameters: dict[str, Any]) -> ToolResponse:
        raise NotImplementedError
