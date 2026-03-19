from __future__ import annotations

from fastapi import APIRouter, Depends

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.search import SearchRequest
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.search_service import search_documents

router = APIRouter(prefix="/search", tags=["search"])


@router.post("")
def search_endpoint(payload: SearchRequest, current_user: User = Depends(get_current_user)):
    del current_user
    documents = [doc.model_dump(mode="json") for doc in search_documents(payload.query, payload.destination, payload.manual_links)]
    return success_response(documents)
