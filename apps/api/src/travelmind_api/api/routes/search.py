from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.search import SearchRequest
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.search_connector import resolve_search_service_config
from travelmind_api.services.search_service import search_documents
from travelmind_api.services.xhs_account import get_xhs_account_status

router = APIRouter(prefix="/search", tags=["search"])


@router.post("")
def search_endpoint(payload: SearchRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    documents = [
        doc.model_dump(mode="json")
        for doc in search_documents(
            payload.query,
            payload.destination,
            payload.manual_links,
            interests=payload.interests,
            search_service_config=resolve_search_service_config(current_user),
            xhs_source_enabled=bool(getattr(current_user, "xhs_source_enabled", False)),
            xhs_user_id=current_user.id,
        )
    ]
    xhs_status = get_xhs_account_status(db, current_user)
    return success_response(documents, meta=xhs_status.model_dump(mode="json"))
