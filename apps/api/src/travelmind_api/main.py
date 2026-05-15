from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from travelmind_api.api.router import router
from travelmind_api.api.routes import mcp as mcp_route
from travelmind_api.api.schemas.common import Envelope, ErrorPayload
from travelmind_api.core.config import get_settings
from travelmind_api.core.database import init_db
from travelmind_api.core.logging_utils import configure_application_logging, log_job_event
from travelmind_api.services.image_storage import IMAGE_FILES_ROUTE


settings = get_settings()


def create_app() -> FastAPI:
    configure_application_logging(settings)
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.mount("/exports/files", StaticFiles(directory=settings.resolved_export_root), name="exports-files")
    app.mount(IMAGE_FILES_ROUTE, StaticFiles(directory=settings.resolved_image_root), name="image-files")
    app.include_router(mcp_route.router)
    app.include_router(router, prefix=settings.api_prefix)

    @app.on_event("startup")
    def on_startup() -> None:
        configure_application_logging(settings)
        log_job_event(
            "api_startup",
            logger_name="travelmind_api.main",
            message="TravelMind API startup initialized.",
            queue_mode=settings.queue_mode,
            agent_provider=settings.agent_provider,
        )
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
        log_job_event(
            "api_unhandled_exception",
            logger_name="travelmind_api.main",
            level="ERROR",
            message=str(exc),
            exception_type=exc.__class__.__name__,
        )
        envelope = Envelope(
            data=None,
            error=ErrorPayload(code="internal_error", message=str(exc)),
            meta={},
        )
        return JSONResponse(status_code=500, content=envelope.model_dump(mode="json"))

    return app


app = create_app()
