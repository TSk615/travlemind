from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.settings import RuntimeSettingsUpdateRequest
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.auth_service import serialize_runtime_settings, update_user_runtime_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("/llm")
def get_llm_settings(current_user: User = Depends(get_current_user), settings: Settings = Depends(get_settings)):
    runtime = serialize_runtime_settings(current_user, settings)
    if current_user.generation_quota is not None:
        # Even key prefixes/suffixes and secret lengths need not be public.
        runtime.agent.api_key_masked = "configured" if runtime.agent.has_api_key else None
        runtime.agent.poi_api_key_masked = "configured" if runtime.agent.poi_has_api_key else None
        runtime.search.api_key_masked = "configured" if runtime.search.has_api_key else None
        runtime.image.api_key_masked = "configured" if runtime.image.has_api_key else None
    return success_response(runtime.model_dump(mode="json"))


@router.put("/llm")
def update_llm_settings_endpoint(
    payload: RuntimeSettingsUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    user = update_user_runtime_settings(db, current_user, payload)
    return success_response(serialize_runtime_settings(user, settings).model_dump(mode="json"))
