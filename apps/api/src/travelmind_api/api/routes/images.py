from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.orm import Session

from travelmind_api.api.schemas.common import success_response
from travelmind_api.api.schemas.images import (
    ImageGenerationStartResponse,
    ImageGenerationUpdateRequest,
    ImagePromptComposeRequest,
    ImagePromptComposeResponse,
)
from travelmind_api.core.config import Settings, get_settings
from travelmind_api.core.database import get_db
from travelmind_api.core.deps import get_current_user
from travelmind_api.db.models import User
from travelmind_api.services.image_generation import (
    create_image_generation,
    create_image_remix,
    get_owned_image_generation_or_404,
    get_visible_image_generation_or_404,
    list_public_image_generations,
    list_user_image_generations,
    serialize_image_generation,
    update_image_generation,
)
from travelmind_api.services.image_prompt_service import ImagePromptComposePayload, compose_image_prompt
from travelmind_api.services.image_storage import persist_upload_file
from travelmind_api.services.job_service import create_job, dispatch_job, serialize_job
from travelmind_api.services.llm import LlmConfig

router = APIRouter(prefix="/images", tags=["images"])


def _parse_json_list(value: str | None) -> list[Any]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _resolve_text_llm_config(user: User) -> LlmConfig | None:
    return LlmConfig.from_mapping(
        {
            "base_url": user.llm_base_url,
            "api_key": user.llm_api_key,
            "model": user.llm_model,
            "wire_api": user.llm_wire_api,
            "provider_protocol": getattr(user, "llm_provider_protocol", None),
        }
    )


@router.post("/prompts/compose")
def compose_image_prompt_endpoint(payload: ImagePromptComposeRequest, current_user: User = Depends(get_current_user)):
    result = compose_image_prompt(
        ImagePromptComposePayload(
            title=payload.title,
            destination=payload.destination,
            scene_prompt=payload.scene_prompt,
            prompt=payload.prompt,
            negative_prompt=payload.negative_prompt,
            style_tags=payload.style_tags,
            reference_urls=payload.reference_urls,
            reference_count=payload.reference_count,
        ),
        _resolve_text_llm_config(current_user),
    )
    return success_response(ImagePromptComposeResponse(**result.__dict__).model_dump(mode="json"))


@router.post("/generate")
async def generate_image_endpoint(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    current_user: User = Depends(get_current_user),
    title: str = Form(default=""),
    destination: str = Form(default=""),
    scene_prompt: str = Form(default=""),
    mode: str = Form(default="text_to_image"),
    visibility: str = Form(default="private"),
    prompt: str = Form(default=""),
    optimized_prompt: str = Form(default=""),
    negative_prompt: str = Form(default=""),
    style_tags_json: str = Form(default="[]"),
    reference_urls_json: str = Form(default="[]"),
    source_image: UploadFile | None = File(default=None),
    reference_files: list[UploadFile] = File(default=[]),
):
    style_tags = [str(item).strip() for item in _parse_json_list(style_tags_json) if str(item).strip()]
    reference_urls = [str(item).strip() for item in _parse_json_list(reference_urls_json) if str(item).strip()]
    if mode == "image_to_image" and source_image is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"code": "missing_source_image", "message": "source_image is required for image_to_image"},
        )
    source_assets: list[dict[str, str]] = []
    if source_image is not None:
        source_assets.append(await persist_upload_file(source_image, settings=settings, bucket="uploads", owner_user_id=current_user.id))
    reference_assets: list[dict[str, Any]] = []
    for upload in reference_files:
        reference_assets.append(await persist_upload_file(upload, settings=settings, bucket="uploads", owner_user_id=current_user.id))
    reference_assets.extend(
        {
            "id": f"ref_url_{index}",
            "url": url,
            "path": None,
            "filename": None,
            "mime_type": None,
        }
        for index, url in enumerate(reference_urls)
    )

    record = create_image_generation(
        db,
        user=current_user,
        title=title,
        destination=destination,
        scene_prompt=scene_prompt,
        mode=mode,
        visibility=visibility,
        prompt=prompt,
        optimized_prompt=optimized_prompt,
        negative_prompt=negative_prompt,
        style_tags=style_tags,
        source_images=source_assets,
        reference_images=reference_assets,
        status="queued",
    )
    job = create_job(
        db,
        job_type="image.generate",
        owner_user_id=current_user.id,
        trip_id=None,
        payload={"generation_id": record.id},
    )
    dispatch_job(job.id, settings, background_tasks)
    response = ImageGenerationStartResponse(
        generation=serialize_image_generation(record),
        job=serialize_job(job),
    )
    return success_response(response.model_dump(mode="json"))


@router.get("")
def get_my_image_generations(
    mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    visibility: str | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    records = [
        serialize_image_generation(record).model_dump(mode="json")
        for record in list_user_image_generations(db, current_user, mode=mode, status=status, visibility=visibility)
    ]
    return success_response(records)


@router.get("/feed")
def get_public_image_feed(
    limit: int = Query(default=24, ge=1, le=60),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    del current_user
    records = [
        serialize_image_generation(record, author_name=author_name).model_dump(mode="json")
        for record, author_name in list_public_image_generations(db, limit=limit)
    ]
    return success_response(records)


@router.get("/prompt-trends")
def get_prompt_trends(
    platform: str = Query(...),
    destination: str | None = Query(default=None),
    limit: int = Query(default=12, ge=1, le=50),
    current_user: User = Depends(get_current_user),
):
    del current_user
    del destination
    del limit
    return success_response([], meta={"implemented": False, "source": "reserved", "platform": platform})


@router.get("/{generation_id}")
def get_image_generation(generation_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    record = get_visible_image_generation_or_404(db, current_user, generation_id)
    author_name = current_user.name if record.user_id == current_user.id else db.query(User.name).filter(User.id == record.user_id).scalar()
    return success_response(serialize_image_generation(record, author_name=author_name).model_dump(mode="json"))


@router.patch("/{generation_id}")
def update_image_generation_endpoint(
    generation_id: str,
    payload: ImageGenerationUpdateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = get_owned_image_generation_or_404(db, current_user, generation_id)
    updated = update_image_generation(
        db,
        record,
        title=payload.title,
        destination=payload.destination,
        style_tags=payload.style_tags,
        visibility=payload.visibility,
    )
    return success_response(serialize_image_generation(updated).model_dump(mode="json"))


@router.post("/{generation_id}/remix")
def remix_image_generation(generation_id: str, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    source = get_visible_image_generation_or_404(db, current_user, generation_id)
    cloned = create_image_remix(db, user=current_user, source=source)
    return success_response(serialize_image_generation(cloned, author_name=current_user.name).model_dump(mode="json"))
