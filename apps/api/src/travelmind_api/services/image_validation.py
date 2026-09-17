"""Bounded validation of public image resources, without following private redirects."""
import hashlib
import base64
import ipaddress
import socket
import time
import warnings
from io import BytesIO
from urllib.parse import urljoin, urlparse

import httpx
from PIL import Image

from travelmind_api.services.search_connector import is_public_source_url
from travelmind_api.core.env import get_env

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def public_image_url(url: str) -> bool:
    if not is_public_source_url(url):
        return False
    host = urlparse(url).hostname
    try:
        addresses = socket.getaddrinfo(host, None)
        fake_ip_enabled = str(get_env("TRAVELMIND_IMAGE_ALLOW_FAKE_IP", "false")).lower() in {"1", "true"}
        fake_network = ipaddress.ip_network("198.18.0.0/15")
        return bool(addresses) and all(
            ipaddress.ip_address(row[4][0]).is_global
            or (fake_ip_enabled and ipaddress.ip_address(row[4][0]) in fake_network)
            for row in addresses
        )
    except (OSError, ValueError):
        return False


def inspect_image_bytes(data: bytes) -> dict:
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("图片超过8MB")
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(data)) as picture:
            width, height = picture.size
            if width * height > 30_000_000 or min(width, height) < 240 or max(width, height) < 480:
                raise ValueError("图片尺寸不适合作为景点配图")
            if max(width, height) / min(width, height) > 4:
                raise ValueError("图片比例不适合作为景点配图")
            picture.verify()
        with Image.open(BytesIO(data)) as picture:
            picture.load()
            preview = picture.convert("RGB")
            preview.thumbnail((768, 768))
            buffer = BytesIO()
            preview.save(buffer, format="JPEG", quality=80)
    return {"width": width, "height": height, "sha256": hashlib.sha256(data).hexdigest(),
            "preview_data_url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")}


def validate_image_url(url: str) -> tuple[dict | None, str | None]:
    try:
        with httpx.Client(timeout=6, follow_redirects=False, trust_env=False) as client:
            rate_limit_retries = 0
            for _ in range(4):
                if not public_image_url(url):
                    return None, "图片地址不是公开网络资源"
                with client.stream(
                    "GET",
                    url,
                    headers={
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                        "User-Agent": "TravelMind/1.0 (+public itinerary image validation)",
                    },
                ) as response:
                    if response.status_code == 429 and rate_limit_retries < 1:
                        rate_limit_retries += 1
                        try:
                            retry_after = float(response.headers.get("retry-after") or 1)
                        except ValueError:
                            retry_after = 1
                        time.sleep(min(max(retry_after, 0.25), 2.0))
                        continue
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    response.raise_for_status()
                    if not response.headers.get("content-type", "").lower().startswith("image/"):
                        return None, "响应不是图片"
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data) > MAX_IMAGE_BYTES:
                            return None, "图片超过8MB"
                    return inspect_image_bytes(bytes(data)), None
        return None, "图片重定向次数过多"
    except httpx.HTTPStatusError as exc:
        return None, f"图片请求返回 HTTP {exc.response.status_code}"
    except (ValueError, OSError) as exc:
        detail = str(exc).strip()
        return None, f"图片无法加载或解码：{detail or type(exc).__name__}"
    except Exception as exc:
        return None, f"图片无法加载或解码：{type(exc).__name__}"
