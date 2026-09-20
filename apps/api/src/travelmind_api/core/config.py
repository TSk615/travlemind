from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


DEFAULT_JWT_SECRET = "travelmind-dev-secret-change-me-32-bytes-minimum"
DEFAULT_CREDENTIAL_ENCRYPTION_KEY = "travelmind-dev-credential-key-change-me-32-bytes"


class Settings(BaseSettings):
    app_name: str = "TravelMind AI API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./storage/travelmind.db"
    workflow_checkpoint_url: str | None = None
    jwt_secret: str = DEFAULT_JWT_SECRET
    credential_encryption_key: str = DEFAULT_CREDENTIAL_ENCRYPTION_KEY
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    access_cookie_name: str = "travelmind_access"
    refresh_cookie_name: str = "travelmind_refresh"
    csrf_cookie_name: str = "travelmind_csrf"
    csrf_header_name: str = "X-CSRF-Token"
    csrf_enabled: bool = True
    cookie_secure: bool | None = None
    cookie_samesite: Literal["lax", "strict", "none"] = "lax"
    xhs_session_secret: str = ""
    queue_mode: str = "inline"
    redis_url: str = "redis://127.0.0.1:6379/0"
    rate_limit_enabled: bool = True
    rate_limit_backend: Literal["memory", "redis"] = "memory"
    rate_limit_window_seconds: int = 60
    rate_limit_default_requests: int = 240
    rate_limit_auth_requests: int = 10
    rate_limit_expensive_requests: int = 30
    job_max_attempts: int = 3
    job_timeout_seconds: int = 900
    job_retry_base_seconds: int = 5
    job_heartbeat_seconds: int = 15
    job_stale_after_seconds: int = 120
    job_result_ttl_seconds: int = 86400
    worker_max_jobs: int = 8
    agent_provider: str = "standard"
    langgraph_rollout_percent: int = Field(default=100, ge=0, le=100)
    langgraph_rollout_fallback_provider: Literal["standard"] = "standard"
    log_level: str = "INFO"
    log_root: str | None = None
    export_root: str | None = None
    image_root: str | None = None
    public_api_url: str = "http://127.0.0.1:8000"
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]
    admin_emails: str = "zhMarch@marchxyz.com"
    upstream_private_url_policy: str = "loopback"
    upstream_url_allowed_hosts: str = ""

    model_config = SettingsConfigDict(
        env_prefix="TRAVELMIND_",
        env_file=".env",
        extra="ignore"
    )

    @field_validator("environment", mode="before")
    @classmethod
    def normalize_environment(cls, value: str) -> str:
        return str(value or "development").strip().lower()

    @model_validator(mode="after")
    def validate_security_configuration(self) -> "Settings":
        if self.cookie_samesite == "none" and not self.auth_cookie_secure:
            raise ValueError("SameSite=None cookies require TRAVELMIND_COOKIE_SECURE=true")

        if not self.is_production:
            return self

        errors: list[str] = []
        if self.jwt_secret == DEFAULT_JWT_SECRET or len(self.jwt_secret) < 32:
            errors.append("TRAVELMIND_JWT_SECRET must be a non-default secret with at least 32 characters")
        if self.credential_encryption_key == DEFAULT_CREDENTIAL_ENCRYPTION_KEY or len(self.credential_encryption_key) < 32:
            errors.append("TRAVELMIND_CREDENTIAL_ENCRYPTION_KEY must be a non-default secret with at least 32 characters")
        if not self.auth_cookie_secure:
            errors.append("TRAVELMIND_COOKIE_SECURE must not disable Secure cookies")
        if urlparse(self.public_api_url).scheme.lower() != "https":
            errors.append("TRAVELMIND_PUBLIC_API_URL must use https in production")
        insecure_origins = [origin for origin in self.cors_origins if urlparse(origin).scheme.lower() != "https"]
        if insecure_origins or "*" in self.cors_origins:
            errors.append("TRAVELMIND_CORS_ORIGINS must contain explicit https origins in production")
        if self.upstream_private_url_policy.strip().lower() != "deny":
            errors.append("TRAVELMIND_UPSTREAM_PRIVATE_URL_POLICY must be deny in production")
        if self.database_url.strip().lower().startswith("sqlite"):
            errors.append("TRAVELMIND_DATABASE_URL must use PostgreSQL in production")
        checkpoint_url = str(self.workflow_checkpoint_url or self.database_url).strip().lower()
        if not checkpoint_url.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            errors.append("TRAVELMIND_WORKFLOW_CHECKPOINT_URL must use PostgreSQL in production")
        if not self.csrf_enabled:
            errors.append("TRAVELMIND_CSRF_ENABLED must be true in production")
        if not self.rate_limit_enabled or self.rate_limit_backend != "redis":
            errors.append("Production rate limiting must be enabled with the Redis backend")
        if self.job_max_attempts < 2 or self.job_timeout_seconds < 60:
            errors.append("Production jobs require at least two attempts and a timeout of at least 60 seconds")
        if errors:
            raise ValueError("Invalid production security configuration: " + "; ".join(errors))
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def auth_cookie_secure(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.is_production

    @property
    def project_root(self) -> Path:
        # Keep all repo-local defaults anchored to the workspace root, even when
        # the app is imported from an editable install inside the virtualenv.
        return Path(__file__).resolve().parents[5]

    @property
    def resolved_export_root(self) -> Path:
        # MVP exports default to repo-local storage so local runs and tests do
        # not need object storage before the deployment layer is in place.
        if self.export_root:
            path = Path(self.export_root)
        else:
            path = self.project_root / "storage" / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def resolved_image_root(self) -> Path:
        if self.image_root:
            path = Path(self.image_root)
        else:
            path = self.project_root / "storage" / "images"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def resolved_log_root(self) -> Path:
        if self.log_root:
            path = Path(self.log_root)
        else:
            path = self.project_root / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @property
    def resolved_workflow_checkpoint_url(self) -> str:
        """Return the dedicated LangGraph checkpoint store location.

        Local and test deployments use an independent SQLite file. Production
        already requires PostgreSQL, so the application database URL is reused
        there while LangGraph keeps its own checkpoint tables.
        """

        configured = str(self.workflow_checkpoint_url or "").strip()
        if configured:
            return configured
        database_url = self.database_url.strip()
        if database_url.lower().startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
            return database_url.replace("postgresql+psycopg://", "postgresql://", 1)
        path = self.project_root / "storage" / "langgraph-checkpoints.db"
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    @property
    def normalized_admin_emails(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
