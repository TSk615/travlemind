from __future__ import annotations

from fastapi import APIRouter, Depends

from travelmind_api.api.schemas.common import success_response
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.auth_service import serialize_user

router = APIRouter(tags=["account"])


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return success_response(serialize_user(current_user).model_dump(mode="json"))
