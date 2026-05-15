from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote, urljoin

from fastapi import UploadFile

from travelmind_api.core.config import Settings
from travelmind_api.core.security import generate_identifier


IMAGE_FILES_ROUTE = "/images/files"


def _guess_extension(filename: str | None, mime_type: str | None) -> str:
    if filename:
        suffix = Path(filename).suffix.strip()
        if suffix:
            return suffix
    guessed = mimetypes.guess_extension(mime_type or "")
    return guessed or ".bin"


def _build_file_url(settings: Settings, relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    return urljoin(f"{settings.public_api_url.rstrip('/')}/", f"{IMAGE_FILES_ROUTE}/{quote(normalized)}")


def persist_bytes(
    data: bytes,
    *,
    settings: Settings,
    bucket: str,
    owner_user_id: str,
    filename: str | None = None,
    mime_type: str | None = None,
) -> dict[str, str]:
    bucket_dir = settings.resolved_image_root / bucket / owner_user_id
    bucket_dir.mkdir(parents=True, exist_ok=True)
    extension = _guess_extension(filename, mime_type)
    generated_name = f"{generate_identifier('img')}{extension}"
    absolute_path = bucket_dir / generated_name
    absolute_path.write_bytes(data)
    relative_path = absolute_path.relative_to(settings.resolved_image_root).as_posix()
    return {
        "id": generate_identifier("ast"),
        "url": _build_file_url(settings, relative_path),
        "path": relative_path,
        "filename": filename or generated_name,
        "mime_type": mime_type or "application/octet-stream",
    }


async def persist_upload_file(upload: UploadFile, *, settings: Settings, bucket: str, owner_user_id: str) -> dict[str, str]:
    data = await upload.read()
    return persist_bytes(
        data,
        settings=settings,
        bucket=bucket,
        owner_user_id=owner_user_id,
        filename=upload.filename,
        mime_type=upload.content_type,
    )
