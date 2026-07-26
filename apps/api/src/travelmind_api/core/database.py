from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from travelmind_api.core.config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=connect_args, future=True, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


def alembic_config(database_url: str | None = None) -> Config:
    api_root = Path(__file__).resolve().parents[3]
    config = Config(str(api_root / "alembic.ini"))
    config.set_main_option("script_location", (api_root / "migrations").as_posix())
    config.set_main_option("sqlalchemy.url", (database_url or settings.database_url).replace("%", "%%"))
    return config


def init_db() -> None:
    from travelmind_api.db import models  # noqa: F401
    from travelmind_api.core.credentials import migrate_legacy_plaintext_credentials

    command.upgrade(alembic_config(), "head")
    migrate_legacy_plaintext_credentials(engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope():
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
