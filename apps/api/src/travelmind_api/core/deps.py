from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.core.security import decode_access_token
from travelmind_api.db.models import User


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = request.cookies.get(settings.access_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "not_authenticated", "message": "Authentication required"})

    try:
        payload = decode_access_token(token, settings)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "invalid_token", "message": "Invalid session token"}) from exc

    user = db.scalar(select(User).where(User.id == payload.get("sub")))
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail={"code": "user_not_found", "message": "User not found"})
    return user
