# GrokSearch Bridge Deploy

## Summary

TravelMind now includes a dedicated `groksearch-bridge` service that installs the upstream `GuDaStudio/GrokSearch` project from the `grok-with-tavily` branch during image build and exposes it as an HTTP JSON-RPC MCP endpoint.

## Compose

Run from repo root:

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml up --build groksearch-bridge api worker web
```

Bridge endpoint inside Compose:

```text
http://groksearch-bridge:8085/mcp
```

Bridge endpoint on host:

```text
http://localhost:8085/mcp
```

## Required Settings

At least one of the upstream auth paths must be configured:

- `GUDA_API_KEY`
- or `GROK_API_KEY`

Optional enrichers:

- `TAVILY_API_KEY`
- `FIRECRAWL_API_KEY`

TravelMind-side bridge auth:

- `TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY`

To make backend search default to GrokSearch:

```powershell
$env:TRAVELMIND_SEARCH_SERVICE_PROVIDER="groksearch"
$env:TRAVELMIND_SEARCH_SERVICE_TRANSPORT="mcp"
```

Or save `provider=groksearch` in the app settings UI.

## Build Source

The bridge image installs upstream GrokSearch from:

- `GROKSEARCH_GIT_URL`
- `GROKSEARCH_REF`

Defaults:

- `https://github.com/GuDaStudio/GrokSearch`
- `grok-with-tavily`
