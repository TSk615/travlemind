import json

import httpx

from travelmind_api.services.xhs_crawler import (
    XhsCrawlerBindingState,
    XhsCrawlerClient,
    XhsCrawlerConfig,
    XhsCrawlerSessionExpiredError,
)


def test_xhs_crawler_client_starts_binding():
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("Authorization"),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(
            200,
            json={
                "bind_id": "xhb_test",
                "status": "pending",
                "verification_url": "https://example.test/xhs/bind",
                "verification_code": "123456",
                "qr_image_data_url": "data:image/png;base64,abcd",
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = XhsCrawlerClient(
        XhsCrawlerConfig(base_url="https://crawler.example.test", api_key="crawler-key", timeout_seconds=10.0),
        http_client=http_client,
    )

    try:
        binding = client.start_binding(user_id="usr_1")
    finally:
        http_client.close()

    assert isinstance(binding, XhsCrawlerBindingState)
    assert binding.bind_id == "xhb_test"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://crawler.example.test/internal/xhs/bind/start"
    assert calls[0]["authorization"] == "Bearer crawler-key"
    assert calls[0]["payload"] == {"user_id": "usr_1"}


def test_xhs_crawler_client_calls_session_search_and_uses_cache():
    calls: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(
            {
                "url": str(request.url),
                "authorization": request.headers.get("Authorization"),
                "payload": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(
            200,
            json={
                "posts": [
                    {
                        "post_id": "xhs_1",
                        "title": "Kyoto calm walk guide",
                        "url": "https://www.xiaohongshu.com/explore/xhs_1",
                        "author": "Traveler A",
                        "published_at": "2026-03-10T10:00:00Z",
                        "excerpt": "A calm Kyoto route for first-time visitors.",
                        "engagement_hint": "1.2k likes",
                        "tags": ["Kyoto", "walk"],
                        "raw_destination_hint": "Kyoto",
                    }
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = XhsCrawlerClient(
        XhsCrawlerConfig(
            base_url="https://crawler.example.test",
            api_key="crawler-key",
            timeout_seconds=10.0,
            cache_ttl_seconds=60,
            limit_per_query=5,
            max_results=10,
        ),
        http_client=http_client,
    )

    try:
        first = client.search_posts(
            user_id="usr_1",
            session_payload={"cookies": [{"name": "a", "value": "b"}]},
            destination="Kyoto",
            queries=["Kyoto travel guide"],
            limit_per_query=3,
        )
        second = client.search_posts(
            user_id="usr_1",
            session_payload={"cookies": [{"name": "a", "value": "b"}]},
            destination="Kyoto",
            queries=["Kyoto travel guide"],
            limit_per_query=3,
        )
    finally:
        http_client.close()

    assert len(calls) == 1
    assert calls[0]["url"] == "https://crawler.example.test/internal/xhs/session/search"
    assert calls[0]["authorization"] == "Bearer crawler-key"
    assert calls[0]["payload"] == {
        "user_id": "usr_1",
        "destination": "Kyoto",
        "queries": ["Kyoto travel guide"],
        "limit_per_query": 3,
        "session_payload": {"cookies": [{"name": "a", "value": "b"}]},
    }
    assert first[0].post_id == "xhs_1"
    assert second[0].url == "https://www.xiaohongshu.com/explore/xhs_1"


def test_xhs_crawler_client_maps_expired_session_error():
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(409, json={"detail": {"code": "xhs_session_expired", "message": "Session expired"}})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = XhsCrawlerClient(
        XhsCrawlerConfig(base_url="https://crawler.example.test", timeout_seconds=10.0),
        http_client=http_client,
    )

    try:
        try:
            client.search_posts(
                user_id="usr_1",
                session_payload={"cookies": [{"name": "a", "value": "b"}]},
                destination="Kyoto",
                queries=["Kyoto travel guide"],
            )
        except XhsCrawlerSessionExpiredError as exc:
            assert "Session expired" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("Expected XhsCrawlerSessionExpiredError")
    finally:
        http_client.close()
