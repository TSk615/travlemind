from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    avatar: str | None
    locale: str
    created_at: datetime
    is_admin: bool = False


class LogoutResponse(BaseModel):
    success: bool = True


class RefreshResponse(BaseModel):
    success: bool = True
