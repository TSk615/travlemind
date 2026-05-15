import json
import time

from fastapi.testclient import TestClient


def _register(client: TestClient, *, email: str = "images@example.com"):
    response = client.post(
        "/api/v1/auth/register",
        json={
            "name": "Image User",
            "email": email,
            "password": "supersecure123",
        },
    )
    assert response.status_code == 200, response.text
    return response


def _wait_for_terminal_job(client: TestClient, job_id: str) -> dict:
    payload = None
    for _ in range(30):
        response = client.get(f"/api/v1/jobs/{job_id}")
        assert response.status_code == 200, response.text
        payload = response.json()["data"]
        if payload["status"] in {"completed", "failed"}:
            return payload
        time.sleep(0.05)
    assert payload is not None
    return payload


def _save_image_settings(client: TestClient):
    response = client.put(
        "/api/v1/settings/llm",
        json={
            "image": {
                "base_url": "https://images.example.com/v1",
                "api_key": "img-secret-1234",
                "model": "gpt-image-1",
                "provider": "openai_compatible",
            }
        },
    )
    assert response.status_code == 200, response.text


def test_build_image_provider_supports_expected_supplier_types():
    from travelmind_api.services.images import ImageModelConfig, build_image_provider
    from travelmind_api.services.images.huggingface import HuggingFaceImageProvider
    from travelmind_api.services.images.openai_compatible import OpenAICompatibleImageProvider

    openai_family = ("openai_compatible", "gitee_ai", "modelscope", "a4f")
    for provider in openai_family:
        instance = build_image_provider(
            ImageModelConfig(
                base_url="https://images.example.com/v1",
                api_key="img-secret",
                model="gpt-image-1",
                provider=provider,
            )
        )
        assert isinstance(instance, OpenAICompatibleImageProvider)

    huggingface = build_image_provider(
        ImageModelConfig(
            base_url="https://router.huggingface.co/hf-inference",
            api_key="hf_secret",
            model="black-forest-labs/FLUX.1-Krea-dev",
            provider="huggingface",
        )
    )
    assert isinstance(huggingface, HuggingFaceImageProvider)


def test_image_title_falls_back_to_prompt_when_optional_fields_are_empty():
    from travelmind_api.services.image_generation import build_image_title

    title = build_image_title(title="", destination="", scene_prompt="", prompt="quiet temple path after rain with cinematic lighting")
    assert title.startswith("quiet temple path")


class _StubImageProvider:
    def generate(self, request):
        del request
        from travelmind_api.services.images.base import GeneratedImage

        return [GeneratedImage(data=b"fake-image-bytes", mime_type="image/png")]


def test_image_generate_and_remix_flow(client: TestClient, monkeypatch):
    import travelmind_api.jobs.handlers as job_handlers

    monkeypatch.setattr(job_handlers, "build_image_provider", lambda config: _StubImageProvider())

    _register(client)
    _save_image_settings(client)

    response = client.post(
        "/api/v1/images/generate",
        data={
            "title": "Kyoto mood cover",
            "destination": "Kyoto",
            "scene_prompt": "quiet temple path after rain",
            "mode": "text_to_image",
            "visibility": "public",
            "prompt": "cinematic quiet temple path",
            "optimized_prompt": "",
            "negative_prompt": "blurry",
            "style_tags_json": json.dumps(["cinematic", "travel"]),
            "reference_urls_json": json.dumps(["https://example.com/ref-1"]),
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["job"]["type"] == "image.generate"
    assert payload["generation"]["status"] == "queued"

    job = _wait_for_terminal_job(client, payload["job"]["job_id"])
    assert job["status"] == "completed", job

    detail_response = client.get(f"/api/v1/images/{payload['generation']['id']}")
    assert detail_response.status_code == 200, detail_response.text
    detail = detail_response.json()["data"]
    assert detail["status"] == "completed"
    assert detail["visibility"] == "public"
    assert len(detail["result_images"]) == 1

    remix_response = client.post(f"/api/v1/images/{detail['id']}/remix")
    assert remix_response.status_code == 200, remix_response.text
    remixed = remix_response.json()["data"]
    assert remixed["status"] == "draft"
    assert remixed["remix_from_id"] == detail["id"]

    feed_response = client.get("/api/v1/images/feed")
    assert feed_response.status_code == 200, feed_response.text
    feed = feed_response.json()["data"]
    assert len(feed) == 1
    assert feed[0]["id"] == detail["id"]
    assert feed[0]["remix_count"] == 1


def test_image_to_image_requires_source_upload(client: TestClient):
    _register(client)
    _save_image_settings(client)

    response = client.post(
        "/api/v1/images/generate",
        data={
            "title": "Need source",
            "destination": "Kyoto",
            "scene_prompt": "portrait",
            "mode": "image_to_image",
            "visibility": "private",
            "prompt": "portrait illustration",
            "optimized_prompt": "",
            "negative_prompt": "",
            "style_tags_json": "[]",
            "reference_urls_json": "[]",
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "missing_source_image"


def test_prompt_trends_placeholder_returns_empty_meta(client: TestClient):
    _register(client)

    response = client.get("/api/v1/images/prompt-trends?platform=douyin&limit=5")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data"] == []
    assert payload["meta"] == {
        "implemented": False,
        "source": "reserved",
        "platform": "douyin",
    }
