from __future__ import annotations

from fastapi import FastAPI, HTTPException

from .config import Settings
from .schemas import InternalXhsBindStartRequest, InternalXhsBindingState, InternalXhsSessionSearchRequest, XhsSearchResponse
from .service import OpenCliRunnerError, XhsBrowserNodeService, XhsSessionExpiredError

settings = Settings()
runner = XhsBrowserNodeService(settings)
app = FastAPI(title="TravelMind XHS Browser Node", version="0.2.0")


@app.get("/health")
def health() -> dict:
    return {"status": "ok", **runner.health()}


@app.post("/internal/xhs/bind/start", response_model=InternalXhsBindingState)
def internal_xhs_bind_start(payload: InternalXhsBindStartRequest) -> InternalXhsBindingState:
    try:
        return runner.start_binding(user_id=payload.user_id)
    except OpenCliRunnerError as exc:
        raise HTTPException(status_code=502, detail={"code": "xhs_bind_start_failed", "message": str(exc)}) from exc


@app.get("/internal/xhs/bind/{bind_id}", response_model=InternalXhsBindingState)
def internal_xhs_bind_status(bind_id: str) -> InternalXhsBindingState:
    try:
        return runner.get_binding(bind_id=bind_id)
    except OpenCliRunnerError as exc:
        raise HTTPException(status_code=502, detail={"code": "xhs_bind_poll_failed", "message": str(exc)}) from exc


@app.post("/internal/xhs/session/search", response_model=XhsSearchResponse)
def internal_xhs_session_search(payload: InternalXhsSessionSearchRequest) -> XhsSearchResponse:
    try:
        return runner.search_session(payload)
    except XhsSessionExpiredError as exc:
        raise HTTPException(status_code=409, detail={"code": "xhs_session_expired", "message": str(exc)}) from exc
    except OpenCliRunnerError as exc:
        raise HTTPException(status_code=502, detail={"code": "xhs_search_failed", "message": str(exc)}) from exc


@app.post("/internal/xhs/session/search-debug")
def internal_xhs_session_search_debug(payload: InternalXhsSessionSearchRequest) -> dict:
    try:
        return runner.search_session_debug(payload)
    except XhsSessionExpiredError as exc:
        raise HTTPException(status_code=409, detail={"code": "xhs_session_expired", "message": str(exc)}) from exc
    except OpenCliRunnerError as exc:
        raise HTTPException(status_code=502, detail={"code": "xhs_search_failed", "message": str(exc)}) from exc


@app.delete("/internal/xhs/session/{user_id}")
def internal_xhs_session_delete(user_id: str) -> dict[str, bool]:
    try:
        runner.delete_session(user_id=user_id)
    except OpenCliRunnerError as exc:
        raise HTTPException(status_code=502, detail={"code": "xhs_session_delete_failed", "message": str(exc)}) from exc
    return {"success": True}
