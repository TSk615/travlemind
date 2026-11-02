import asyncio
from types import SimpleNamespace

import pytest

from travelmind_groksearch_bridge.search_resilience import install_bounded_primary_search


def test_slow_grok_does_not_hide_completed_tavily_sources():
    state = {"cancelled": False}
    class Provider:
        async def search(self, query, platform=""):
            try:
                await asyncio.sleep(60)
            finally:
                state["cancelled"] = True
    module = SimpleNamespace(GrokSearchProvider=Provider)
    install_bounded_primary_search(module, timeout_seconds=.03)

    async def web_search():
        # This is the actual upstream control flow: gather waits for all branches.
        async def safe_grok():
            try:
                return await module.GrokSearchProvider().search("fixture")
            except Exception:
                return ""
        async def tavily():
            return [{"url": "https://source.example/poi", "title": "来源标题", "content": "来源正文"}]
        return await asyncio.wait_for(asyncio.gather(safe_grok(), tavily()), timeout=.5)

    answer, sources = asyncio.run(web_search())
    assert answer == "" and sources[0]["content"] == "来源正文"
    assert state["cancelled"] is True


def test_successful_grok_is_unchanged_and_installation_is_idempotent():
    class Provider:
        async def search(self, query, platform=""):
            return query + platform
    module = SimpleNamespace(GrokSearchProvider=Provider)
    install_bounded_primary_search(module, .1)
    installed = Provider.search
    install_bounded_primary_search(module, .2)
    assert Provider.search is installed
    assert asyncio.run(Provider().search("query", "platform")) == "queryplatform"


def test_parent_cancellation_is_not_swallowed():
    class Provider:
        async def search(self, query):
            raise asyncio.CancelledError()
    module = SimpleNamespace(GrokSearchProvider=Provider)
    install_bounded_primary_search(module, .1)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(Provider().search("fixture"))


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf"), 61])
def test_invalid_timeouts_fail_closed(timeout):
    with pytest.raises(ValueError):
        install_bounded_primary_search(SimpleNamespace(), timeout)

class Cache:
    def __init__(self):
        self.rows = {}
    async def get(self, session):
        return self.rows.get(session)
    async def set(self, session, rows):
        self.rows[session] = rows


def fake_server(behavior="error", extras=None, slow_extras=False):
    cache = Cache()
    class Provider:
        async def search(self, query, platform=""):
            if behavior == "timeout":
                await asyncio.sleep(60)
            if behavior == "error":
                raise RuntimeError("PRIVATE_KEY_AND_PROVIDER_URL_MUST_NOT_LEAK")
            if behavior == "empty":
                return ""
            return "healthy answer"
    module = SimpleNamespace(GrokSearchProvider=Provider, _SOURCES_CACHE=cache)
    async def web_search(query, platform="", model="", extra_sources=0):
        async def primary():
            try:
                return await Provider().search(query, platform)
            except Exception:
                return ""
        async def extra():
            if slow_extras:
                await asyncio.sleep(60)
            return extras or []
        answer, rows = await asyncio.gather(primary(), extra())
        if answer:
            rows = [{"title": "Grok", "url": "https://grok.example/evidence", "content": "grounded"}] + rows
        await cache.set(query, rows)
        return {"session_id": query, "content": answer, "sources_count": len(rows)}
    module.web_search = web_search
    return module


@pytest.mark.parametrize("behavior", ["error", "timeout", "empty"])
def test_exa_takes_over_primary_failures_and_caches_evidence(behavior):
    from travelmind_groksearch_bridge.search_resilience import install_search_fallback
    module = fake_server(behavior)
    calls = []
    async def exa(query, key, **kwargs):
        calls.append((query, key))
        return [{"title": "汕头景点", "url": "https://exa.example/poi", "content": "可用正文", "source": "exa"}]
    install_search_fallback(module, exa_api_key="fixture-secret", primary_timeout_seconds=.01, exa_search=exa)
    result = asyncio.run(module.web_search("汕头旅游"))
    assert result["search_provider"] == "exa"
    assert result["sources_count"] == 1 and "可用正文" in result["content"]
    assert module._SOURCES_CACHE.rows[result["session_id"]] == result["sources"]
    assert calls == [("汕头旅游", "fixture-secret")]
    assert "PRIVATE_KEY" not in str(result) and "fixture-secret" not in str(result)


def test_healthy_grok_does_not_call_exa():
    from travelmind_groksearch_bridge.search_resilience import install_search_fallback
    module = fake_server("success")
    async def exa(*args, **kwargs):
        pytest.fail("Healthy Grok must not spend Exa credits")
    original = module.web_search
    install_search_fallback(module, exa_api_key="test", exa_search=exa)
    wrapped = module.web_search
    install_search_fallback(module, exa_api_key="test", exa_search=exa)
    assert module.web_search is wrapped
    assert asyncio.run(module.web_search("query")) == {"session_id": "query", "content": "healthy answer", "sources_count": 1}
    import inspect
    assert inspect.signature(original) == inspect.signature(wrapped)


def test_exa_merge_preserves_tavily_and_deduplicates():
    from travelmind_groksearch_bridge.search_resilience import install_search_fallback
    module = fake_server(extras=[{"title": "Tavily", "url": "https://evidence.example/one", "content": "原有正文", "source": "tavily"}])
    async def exa(*args, **kwargs):
        return [{"url": "https://evidence.example/one"}, {"url": "https://evidence.example/two", "content": "Exa正文"}]
    install_search_fallback(module, exa_api_key="test", exa_search=exa)
    result = asyncio.run(module.web_search("query"))
    assert result["sources_count"] == 2
    assert result["sources"][0]["content"] == "原有正文"
    assert result["sources"][0]["source"] == "tavily"


def test_stuck_upstream_extra_sources_cannot_block_exa():
    from travelmind_groksearch_bridge.search_resilience import install_search_fallback
    module = fake_server("timeout", slow_extras=True)
    async def exa(*args, **kwargs):
        return [{"url": "https://evidence.example/poi", "content": "fallback"}]
    install_search_fallback(module, exa_api_key="test", primary_timeout_seconds=.01, upstream_timeout_seconds=.03, exa_search=exa)
    async def run():
        return await asyncio.wait_for(module.web_search("query"), .3)
    assert asyncio.run(run())["search_provider"] == "exa"


@pytest.mark.parametrize("extras", [[], [{"url": "https://tavily.example/poi", "content": "available", "source": "tavily"}]])
def test_exa_failure_is_safe_and_keeps_other_available_evidence(extras, caplog):
    from travelmind_groksearch_bridge.search_resilience import install_search_fallback
    module = fake_server(extras=extras)
    async def exa(*args, **kwargs):
        raise RuntimeError("fixture-secret and private endpoint")
    install_search_fallback(module, exa_api_key="fixture-secret", exa_search=exa)
    result = asyncio.run(module.web_search("query"))
    assert result["sources_count"] == len(extras)
    if extras:
        assert result["search_provider"] == "upstream_sources"
    else:
        assert result["error"] == "search_unavailable"
    assert "fixture-secret" not in caplog.text + str(result)


def test_parent_cancellation_does_not_trigger_or_swallow_fallback():
    from travelmind_groksearch_bridge.search_resilience import install_search_fallback
    module = fake_server("timeout")
    calls = []
    async def exa(*args, **kwargs):
        calls.append(True)
        return []
    install_search_fallback(module, exa_api_key="test", exa_search=exa)
    async def run():
        task = asyncio.create_task(module.web_search("query"))
        await asyncio.sleep(.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    asyncio.run(run())
    assert calls == []


def test_exa_request_contract_and_invalid_sources_filtered():
    import httpx
    from travelmind_groksearch_bridge.search_resilience import search_exa
    def handle(request):
        import json
        assert str(request.url) == "https://api.exa.ai/search"
        assert request.headers["x-api-key"] == "test-secret"
        body = json.loads(request.content)
        assert body["query"] == "汕头景点" and body["numResults"] == 6
        assert body["contents"]["text"]["maxCharacters"] == 2500
        return httpx.Response(200, json={"results": [
            {"title": "景点", "url": "https://example.com/poi", "text": "正文", "score": .9},
            {"url": "javascript:alert(1)"}, {"url": "https://user:secret@example.com/private"},
            {"url": "https://example.com/poi"}, None]})
    results = asyncio.run(search_exa("汕头景点", "test-secret", transport=httpx.MockTransport(handle)))
    assert len(results) == 1 and results[0]["content"] == "正文"


def test_concurrent_requests_have_independent_failure_state():
    from travelmind_groksearch_bridge.search_resilience import install_search_fallback
    module = fake_server()
    async def search(self, query, platform=""):
        await asyncio.sleep(.01)
        if query == "bad":
            raise RuntimeError("unavailable")
        return "healthy answer"
    module.GrokSearchProvider.search = search
    calls = []
    async def exa(query, *args, **kwargs):
        calls.append(query)
        return [{"url": "https://example.com/poi", "content": "正文"}]
    install_search_fallback(module, exa_api_key="test", exa_search=exa)
    async def run():
        return await asyncio.gather(module.web_search("bad"), module.web_search("good"))
    bad, good = asyncio.run(run())
    assert bad["search_provider"] == "exa" and good["content"] == "healthy answer"
    assert calls == ["bad"]

@pytest.mark.parametrize("status", [401, 429, 500, 302])
def test_exa_http_failures_are_not_successful_results(status):
    import httpx
    from travelmind_groksearch_bridge.search_resilience import search_exa
    calls = []
    def handle(request):
        calls.append(str(request.url))
        return httpx.Response(status, headers={"Location": "https://untrusted.example/steal"}, json={"results": []})
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(search_exa("query", "test-key", transport=httpx.MockTransport(handle)))
    assert calls == ["https://api.exa.ai/search"]


def test_exa_timeout_returns_explicit_failure_within_request_deadline():
    from travelmind_groksearch_bridge.search_resilience import install_search_fallback
    module = fake_server()
    cancelled = []
    async def exa(*args, **kwargs):
        try:
            await asyncio.sleep(60)
        finally:
            cancelled.append(True)
    install_search_fallback(module, exa_api_key="test", exa_search=exa, exa_timeout_seconds=.01)
    async def run():
        return await asyncio.wait_for(module.web_search("query"), .2)
    assert asyncio.run(run())["error"] == "search_unavailable"
    assert cancelled == [True]
