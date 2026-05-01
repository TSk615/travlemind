from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PromptMessages:
    version: str
    system_prompt: str
    user_prompt: str

    def as_messages(self) -> list[dict[str, str]]:
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.user_prompt},
        ]


@dataclass(frozen=True)
class RolePromptSpec:
    version: str
    system_prompt: str