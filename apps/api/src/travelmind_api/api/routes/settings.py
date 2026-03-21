from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.settings import LlmSettingsUpdateRequest
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.auth_service import serialize_llm_settings, update_user_llm_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/llm")
def get_llm_settings(current_user: User = Depends(get_current_user)):
    return success_response(serialize_llm_settings(current_user).model_dump(mode="json"))


@router.put("/llm")
def update_llm_settings_endpoint(
    payload: LlmSettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user = update_user_llm_settings(db, current_user, payload)
    return success_response(serialize_llm_settings(user).model_dump(mode="json"))
