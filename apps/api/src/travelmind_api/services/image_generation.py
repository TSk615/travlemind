from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.images import ImageGenerationRecordResponse
from travelmind_api.core.security import generate_identifier
from travelmind_api.db.models import ImageGeneration, User

VALID_IMAGE_MODES = {"text_to_image", "image_to_image"}
VALID_IMAGE_VISIBILITIES = {"private", "public"}
VALID_IMAGE_STATUSES = {"draft", "queued", "running", "completed", "failed"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_optional_text(value: str | None) -> str:
    return str(value or "").strip()


def _normalize_tags(values: list[str] | None) -> list[str]:
    if values is None:
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        candidate = str(value or "").strip()
        if not candidate:
            continue
        dedupe = candidate.casefold()
        if dedupe in seen:
            continue
        seen.add(dedupe)
        normalized.append(candidate)
    return normalized


def _validation_error(code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"code": code, "message": message})


def _normalize_mode(value: str) -> str:
    normalized = _normalize_optional_text(value)
    if normalized not in VALID_IMAGE_MODES:
        raise _validation_error("invalid_image_mode", "mode must be text_to_image or image_to_image")
    return normalized


def _normalize_visibility(value: str) -> str:
    normalized = _normalize_optional_text(value) or "private"
    if normalized not in VALID_IMAGE_VISIBILITIES:
        raise _validation_error("invalid_image_visibility", "visibility must be private or public")
    return normalized


def _normalize_status(value: str) -> str:
    normalized = _normalize_optional_text(value) or "draft"
    if normalized not in VALID_IMAGE_STATUSES:
        raise _validation_error("invalid_image_status", "invalid image generation status")
    return normalized


def build_image_title(*, title: str, destination: str, scene_prompt: str, prompt: str = "") -> str:
    normalized_title = title.strip()
    if normalized_title:
        return normalized_title
    normalized_destination = destination.strip()
    if normalized_destination:
        return f"{normalized_destination} travel image"
    normalized_scene = scene_prompt.strip()
    if normalized_scene:
        return f"{normalized_scene[:24]} image"
    normalized_prompt = prompt.strip()
    if normalized_prompt:
        return f"{normalized_prompt[:24]} image"
    return "travel image"


def serialize_image_generation(record: ImageGeneration, author_name: str | None = None) -> ImageGenerationRecordResponse:
    return ImageGenerationRecordResponse(
        id=record.id,
        user_id=record.user_id,
        title=record.title,
        destination=record.destination,
        scene_prompt=record.scene_prompt,
        mode=record.mode,
        status=record.status,
        visibility=record.visibility,
        prompt=record.prompt,
        optimized_prompt=record.optimized_prompt,
        negative_prompt=record.negative_prompt,
        style_tags=list(record.style_tags_json or []),
        source_images=list(record.source_images_json or []),
        reference_images=list(record.reference_images_json or []),
        result_images=list(record.result_images_json or []),
        provider=record.provider,
        model=record.model,
        remix_from_id=record.remix_from_id,
        remix_count=record.remix_count,
        published_at=record.published_at,
        author_name=author_name,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def create_image_generation(
    session: Session,
    *,
    user: User,
    title: str,
    destination: str,
    scene_prompt: str,
    mode: str,
    visibility: str,
    prompt: str,
    optimized_prompt: str | None,
    negative_prompt: str | None,
    style_tags: list[str],
    source_images: list[dict[str, Any]],
    reference_images: list[dict[str, Any]],
    status: str = "queued",
    remix_from_id: str | None = None,
) -> ImageGeneration:
    normalized_mode = _normalize_mode(mode)
    normalized_visibility = _normalize_visibility(visibility)
    normalized_status = _normalize_status(status)
    normalized_title = build_image_title(title=title, destination=destination, scene_prompt=scene_prompt, prompt=prompt)
    published_at = _utcnow() if normalized_visibility == "public" and normalized_status == "completed" else None
    record = ImageGeneration(
        id=generate_identifier("img"),
        user_id=user.id,
        title=normalized_title,
        destination=_normalize_optional_text(destination),
        scene_prompt=_normalize_optional_text(scene_prompt),
        mode=normalized_mode,
        status=normalized_status,
        visibility=normalized_visibility,
        prompt=_normalize_optional_text(prompt),
        optimized_prompt=_normalize_optional_text(optimized_prompt) or None,
        negative_prompt=_normalize_optional_text(negative_prompt) or None,
        style_tags_json=_normalize_tags(style_tags),
        source_images_json=list(source_images),
        reference_images_json=list(reference_images),
        result_images_json=[],
        provider=None,
        model=None,
        remix_from_id=remix_from_id,
        remix_count=0,
        published_at=published_at,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_owned_image_generation_or_404(session: Session, user: User, generation_id: str) -> ImageGeneration:
    record = session.scalar(select(ImageGeneration).where(ImageGeneration.id == generation_id, ImageGeneration.user_id == user.id))
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "image_generation_not_found", "message": "Image generation not found"})
    return record


def get_visible_image_generation_or_404(session: Session, user: User, generation_id: str) -> ImageGeneration:
    record = session.scalar(
        select(ImageGeneration).where(
            ImageGeneration.id == generation_id,
            or_(ImageGeneration.user_id == user.id, ImageGeneration.visibility == "public"),
        )
    )
    if record is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "image_generation_not_found", "message": "Image generation not found"})
    return record


def list_user_image_generations(
    session: Session,
    user: User,
    *,
    mode: str | None = None,
    status: str | None = None,
    visibility: str | None = None,
) -> list[ImageGeneration]:
    query = select(ImageGeneration).where(ImageGeneration.user_id == user.id)
    if mode:
        query = query.where(ImageGeneration.mode == _normalize_mode(mode))
    if status:
        query = query.where(ImageGeneration.status == _normalize_status(status))
    if visibility:
        query = query.where(ImageGeneration.visibility == _normalize_visibility(visibility))
    query = query.order_by(desc(ImageGeneration.created_at))
    return list(session.scalars(query))


def list_public_image_generations(session: Session, *, limit: int = 24) -> list[tuple[ImageGeneration, str | None]]:
    query = (
        select(ImageGeneration, User.name)
        .join(User, User.id == ImageGeneration.user_id)
        .where(ImageGeneration.visibility == "public", ImageGeneration.status == "completed")
        .order_by(desc(ImageGeneration.remix_count), desc(ImageGeneration.published_at), desc(ImageGeneration.created_at))
        .limit(max(1, min(limit, 60)))
    )
    return [(record, author_name) for record, author_name in session.execute(query).all()]


def update_image_generation(
    session: Session,
    record: ImageGeneration,
    *,
    title: str | None,
    destination: str | None,
    style_tags: list[str] | None,
    visibility: str | None,
) -> ImageGeneration:
    next_destination = record.destination
    if destination is not None:
        next_destination = _normalize_optional_text(destination)
        record.destination = next_destination
    if title is not None:
        record.title = build_image_title(title=title, destination=next_destination, scene_prompt=record.scene_prompt, prompt=record.prompt)
    elif destination is not None:
        record.title = build_image_title(title=record.title, destination=next_destination, scene_prompt=record.scene_prompt, prompt=record.prompt)
    if style_tags is not None:
        record.style_tags_json = _normalize_tags(style_tags)
    if visibility is not None:
        normalized_visibility = _normalize_visibility(visibility)
        record.visibility = normalized_visibility
        if normalized_visibility == "public" and record.status == "completed":
            record.published_at = record.published_at or _utcnow()
        if normalized_visibility == "private":
            record.published_at = None
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def create_image_remix(session: Session, *, user: User, source: ImageGeneration) -> ImageGeneration:
    if source.visibility != "public" and source.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail={"code": "image_generation_not_found", "message": "Image generation not found"})
    cloned = ImageGeneration(
        id=generate_identifier("img"),
        user_id=user.id,
        title=f"{source.title} Remix",
        destination=source.destination,
        scene_prompt=source.scene_prompt,
        mode=source.mode,
        status="draft",
        visibility="private",
        prompt=source.prompt,
        optimized_prompt=source.optimized_prompt,
        negative_prompt=source.negative_prompt,
        style_tags_json=list(source.style_tags_json or []),
        source_images_json=[],
        reference_images_json=list(source.reference_images_json or []),
        result_images_json=[],
        provider=source.provider,
        model=source.model,
        remix_from_id=source.id,
        remix_count=0,
        published_at=None,
    )
    source.remix_count = int(source.remix_count or 0) + 1
    session.add(source)
    session.add(cloned)
    session.commit()
    session.refresh(cloned)
    return cloned
