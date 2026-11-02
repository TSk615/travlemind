"""Explicit, idempotent provisioning of a public, five-generation demo account.

Run with python -m travelmind_api.provision_demo --copy-settings-from-email ...
Supply TRAVELMIND_DEMO_PASSWORD in the process environment (never a tracked env).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.security import generate_identifier, hash_password, verify_password
from travelmind_api.db.models import GenerationQuota, User

# Copy only planning/research configuration. Never clone image generation or XHS sessions.
PLANNING_FIELDS = (
    "llm_base_url", "llm_api_key", "llm_model", "llm_wire_api", "llm_provider_protocol", "llm_agent_provider",
    "poi_llm_base_url", "poi_llm_api_key", "poi_llm_model", "poi_llm_wire_api", "poi_llm_provider_protocol",
    "weather_llm_model", "hotel_llm_model", "transport_llm_model",
    "search_service_provider", "search_service_transport", "search_service_base_url",
    "search_service_api_key", "search_service_timeout_seconds",
)


def provision_demo(session: Session, *, email: str, password: str, settings: Settings,
                   copy_settings_from_email: str | None = None,
                   planning_settings: dict | None = None) -> User:
    email = email.strip().lower()
    if not email or "@" not in email or not 8 <= len(password) <= 128:
        raise ValueError("A valid email and an 8–128 character password are required")
    if email in settings.normalized_admin_emails:
        raise ValueError("Public demo accounts must never be administrators")
    existing = session.scalar(select(User).where(User.email == email))
    if existing is not None:
        if existing.generation_quota is None or not verify_password(password, existing.password_hash):
            raise ValueError("Refusing to replace an existing account or reset its password")
        # Re-running deployment never resets usage or changes provider credentials.
        return existing
    if copy_settings_from_email and planning_settings is not None:
        raise ValueError("Choose a source account OR planning settings on stdin")
    if planning_settings is not None:
        if not isinstance(planning_settings, dict) or set(planning_settings) - set(PLANNING_FIELDS):
            raise ValueError("Planning settings contain unsupported fields")
        if not all(planning_settings.get(k) for k in ("llm_base_url", "llm_api_key", "llm_model")):
            raise ValueError("Planning settings require a configured model")
    source = None
    if copy_settings_from_email:
        source = session.scalar(select(User).where(User.email == copy_settings_from_email.strip().lower()))
        if source is None or source.disabled_at is not None:
            raise ValueError("The source planning account does not exist or is disabled")
        if not (source.llm_base_url and source.llm_api_key and source.llm_model):
            raise ValueError("Configure the source planning account before provisioning the demo")
    user = User(id=generate_identifier("usr"), email=email, name="TravelMind 公开体验",
                password_hash=hash_password(password), locale="zh-CN")
    if source is not None:
        for field in PLANNING_FIELDS:
            setattr(user, field, getattr(source, field))
    for field, value in (planning_settings or {}).items():
        setattr(user, field, value)
    user.xhs_source_enabled = False
    user.generation_quota = GenerationQuota(generation_limit=5, used=0)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--email", default="demo@travelmind.example")
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--copy-settings-from-email")
    source.add_argument("--settings-stdin", action="store_true", help="Read private planning settings JSON from stdin")
    args = parser.parse_args()
    password = os.environ.get("TRAVELMIND_DEMO_PASSWORD", "")
    if not password:
        parser.error("Set TRAVELMIND_DEMO_PASSWORD; no account was created")
    from travelmind_api.core.database import SessionLocal, init_db
    init_db()
    with SessionLocal() as session:
        user = provision_demo(session, email=args.email, password=password, settings=get_settings(),
                              copy_settings_from_email=args.copy_settings_from_email,
                              planning_settings=json.load(sys.stdin) if args.settings_stdin else None)
        quota = user.generation_quota
        print(f"Demo ready: {user.email}; remaining={quota.generation_limit - quota.used}/{quota.generation_limit}")


if __name__ == "__main__":
    main()
