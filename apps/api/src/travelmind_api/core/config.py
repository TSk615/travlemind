from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "TravelMind AI API"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./storage/travelmind.db"
    jwt_secret: str = "travelmind-dev-secret-change-me-32-bytes-minimum"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 14
    access_cookie_name: str = "travelmind_access"
    refresh_cookie_name: str = "travelmind_refresh"
    xhs_session_secret: str = ""
    queue_mode: str = "inline"
    redis_url: str = "redis://127.0.0.1:6379/0"
    agent_provider: str = "standard"
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
    def normalized_admin_emails(self) -> set[str]:
        return {email.strip().lower() for email in self.admin_emails.split(",") if email.strip()}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
