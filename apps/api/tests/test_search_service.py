from travelmind_api.services import search_service
from travelmind_api.services.xhs_account import XhsSearchState
from travelmind_api.services.search_connector import SearchServiceConfig
from travelmind_api.services.xhs_crawler import XhsCrawlerConfig, XhsCrawlerPost


def test_search_documents_includes_xhs_and_orders_sources(monkeypatch):
    monkeypatch.setattr(
        search_service.XhsCrawlerConfig,
        "from_env",
        classmethod(lambda cls: XhsCrawlerConfig(base_url="https://crawler.example.test", cache_ttl_seconds=0)),
    )
    monkeypatch.setattr(
        search_service.XhsCrawlerClient,
        "search_posts",
        lambda self, *, user_id, session_payload, destination, queries, limit_per_query=None: [
            XhsCrawlerPost(
                post_id="xhs_1",
                title="Kyoto quiet coffee route",
                url="https://www.xiaohongshu.com/explore/xhs_1",
                author="Traveler A",
                published_at="2026-03-20T10:00:00Z",
                excerpt="Quiet coffee and temple route around Kyoto station.",
                engagement_hint="980 likes",
                tags=["Kyoto", "coffee"],
                raw_destination_hint="Kyoto",
            )
        ],
    )
    monkeypatch.setattr(
        search_service,
        "load_xhs_search_state",
        lambda user_id: XhsSearchState(
            xhs_bound=True,
            xhs_binding_required=False,
            xhs_session_expired=False,
            xhs_message=None,
            session_payload={"cookies": [{"name": "a", "value": "b"}]},
        ),
    )
    monkeypatch.setattr(search_service, "mark_xhs_session_available", lambda user_id: None)

    docs = search_service.search_documents(
        "quiet coffee mornings",
        "Kyoto",
        ["https://example.com/manual"],
        interests=["coffee"],
        social_context="attraction",
        xhs_user_id="usr_1",
    )

    platforms = [doc.platform for doc in docs]
    assert platforms[0] == "official-tourism"
    assert "xiaohongshu" in platforms
    assert platforms.index("xiaohongshu") < platforms.index("manual-link")
    xhs_doc = next(doc for doc in docs if doc.platform == "xiaohongshu")
    assert xhs_doc.author == "Traveler A"
    assert xhs_doc.source_type == "social-guide-post"


def test_search_documents_falls_back_when_xhs_lookup_fails(monkeypatch):
    monkeypatch.setattr(
        search_service.XhsCrawlerConfig,
        "from_env",
        classmethod(lambda cls: XhsCrawlerConfig(base_url="https://crawler.example.test", cache_ttl_seconds=0)),
    )
    monkeypatch.setattr(
        search_service.XhsCrawlerClient,
        "search_posts",
        lambda self, *, user_id, session_payload, destination, queries, limit_per_query=None: (_ for _ in ()).throw(RuntimeError("crawler unavailable")),
    )
    monkeypatch.setattr(
        search_service,
        "load_xhs_search_state",
        lambda user_id: XhsSearchState(
            xhs_bound=True,
            xhs_binding_required=False,
            xhs_session_expired=False,
            xhs_message=None,
            session_payload={"cookies": [{"name": "a", "value": "b"}]},
        ),
    )

    docs = search_service.search_documents("temples", "Kyoto", [], interests=["temples"], social_context="attraction", xhs_user_id="usr_1")

    assert docs
    assert all(doc.platform != "xiaohongshu" for doc in docs)
    assert docs[0].platform == "official-tourism"


def test_search_documents_dedupes_same_xhs_url(monkeypatch):
    monkeypatch.setattr(
        search_service.XhsCrawlerConfig,
        "from_env",
        classmethod(lambda cls: XhsCrawlerConfig(base_url="https://crawler.example.test", cache_ttl_seconds=0, max_results=10)),
    )
    monkeypatch.setattr(
        search_service.XhsCrawlerClient,
        "search_posts",
        lambda self, *, user_id, session_payload, destination, queries, limit_per_query=None: [
            XhsCrawlerPost(
                post_id="xhs_1",
                title="Kyoto route A",
                url="https://www.xiaohongshu.com/explore/xhs_1",
                author="Traveler A",
                excerpt="Route A",
            ),
            XhsCrawlerPost(
                post_id="xhs_2",
                title="Kyoto route B",
                url="https://www.xiaohongshu.com/explore/xhs_1",
                author="Traveler B",
                excerpt="Route B",
            ),
        ],
    )
    monkeypatch.setattr(
        search_service,
        "load_xhs_search_state",
        lambda user_id: XhsSearchState(
            xhs_bound=True,
            xhs_binding_required=False,
            xhs_session_expired=False,
            xhs_message=None,
            session_payload={"cookies": [{"name": "a", "value": "b"}]},
        ),
    )
    monkeypatch.setattr(search_service, "mark_xhs_session_available", lambda user_id: None)

    docs = search_service.search_documents("Kyoto route", "Kyoto", [], interests=["route"], social_context="attraction", xhs_user_id="usr_1")

    assert len([doc for doc in docs if doc.platform == "xiaohongshu"]) == 1


def test_search_documents_include_configured_remote_search_results(monkeypatch):
    monkeypatch.setattr(search_service.ConfiguredSearchGateway, "available_tools", lambda self: {"search"})
    monkeypatch.setattr(
        search_service.ConfiguredSearchGateway,
        "call_operation",
        lambda self, name, arguments: {
            "results": [
                {
                    "title": "Kyoto neighborhood guide",
                    "url": "https://search.example.test/kyoto-guide",
                    "text": "A detailed remote search result with station areas and quiet stays.",
                    "publishedDate": "2026-03-01T00:00:00Z",
                }
            ]
        },
    )

    docs = search_service.search_documents(
        "quiet stays near Kyoto station",
        "Kyoto",
        [],
        search_service_config=SearchServiceConfig(
            provider="exa",
            transport="api",
            base_url="https://search.example.test",
            api_key="test-key",
        ),
        xhs_source_enabled=False,
    )

    remote_doc = next(doc for doc in docs if doc.platform == "exa")
    assert remote_doc.url == "https://search.example.test/kyoto-guide"
    assert remote_doc.source_type == "search-service-api"


def test_search_documents_include_groksearch_sources(monkeypatch):
    monkeypatch.setattr(search_service.ConfiguredSearchGateway, "available_tools", lambda self: {"web_search", "get_sources"})
    monkeypatch.setattr(
        search_service.ConfiguredSearchGateway,
        "call_operation",
        lambda self, name, arguments: {
            "session_id": "session_123",
            "content": "Mock GrokSearch answer",
            "sources": [
                {
                    "title": "Kyoto quiet stays",
                    "url": "https://groksearch.example.test/kyoto-quiet-stays",
                    "snippet": "Quiet boutique hotels near Kyoto Station.",
                    "published_at": "2026-03-05T00:00:00Z",
                }
            ],
        },
    )

    docs = search_service.search_documents(
        "quiet stays near Kyoto station",
        "Kyoto",
        [],
        search_service_config=SearchServiceConfig(
            provider="groksearch",
            transport="mcp",
            base_url="https://groksearch.example.test/mcp",
            api_key="test-key",
        ),
        xhs_source_enabled=False,
    )

    remote_doc = next(doc for doc in docs if doc.platform == "groksearch")
    assert remote_doc.url == "https://groksearch.example.test/kyoto-quiet-stays"
    assert remote_doc.source_type == "search-service-mcp"
