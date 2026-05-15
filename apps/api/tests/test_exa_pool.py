import json

import httpx

from travelmind_api.services.exa_pool import ExaPoolClient, ExaPoolConfig



def test_exa_pool_client_search_uses_x_api_key_header():
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["api_key"] = request.headers.get("x-api-key")
        captured["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"results": [{"title": "Kyoto Guide"}]})

    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    client = ExaPoolClient(ExaPoolConfig(base_url="https://exa.pool.test", api_key="exa-key"), http_client=http_client)

    try:
        response = client.search(query="Kyoto temples", num_results=5, include_text=True)
    finally:
        http_client.close()

    assert captured["url"] == "https://exa.pool.test/search"
    assert captured["api_key"] == "exa-key"
    assert captured["payload"]["query"] == "Kyoto temples"
    assert response["results"][0]["title"] == "Kyoto Guide"
