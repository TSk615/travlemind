from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from travelmind_api.api.router import router
from travelmind_api.api.schemas.common import Envelope, ErrorPayload
from travelmind_api.core.config import get_settings
from travelmind_api.core.database import init_db


settings = get_settings()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/exports/files", StaticFiles(directory=settings.resolved_export_root), name="exports-files")
    app.include_router(router, prefix=settings.api_prefix)

    @app.on_event("startup")
    def on_startup() -> None:
        init_db()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.exception_handler(RequestValidationError)
    async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
        del request
        details = exc.errors()
        first_message = details[0].get("msg", "Request validation failed") if details else "Request validation failed"
        envelope = Envelope(
            data=None,
            error=ErrorPayload(code="request_validation_error", message=first_message, details={"errors": details}),
            meta={},
        )
        return JSONResponse(status_code=422, content=envelope.model_dump(mode="json"))

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        del request
        detail = exc.detail if isinstance(exc.detail, dict) else {"code": "http_error", "message": str(exc.detail)}
        envelope = Envelope(data=None, error=ErrorPayload(**detail), meta={})
        return JSONResponse(status_code=exc.status_code, content=envelope.model_dump(mode="json"))

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        del request
        envelope = Envelope(
            data=None,
            error=ErrorPayload(code="internal_error", message=str(exc)),
            meta={},
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    return app


app = create_app()