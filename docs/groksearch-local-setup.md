# GrokSearch Local Setup

## Goal

This flow prepares a non-Docker local environment so that:

- upstream `grok-search` is installed
- `TRAVELMIND_GROKSEARCH_COMMAND` resolves correctly
- bridge auth and upstream auth are checked before you start services

## One-command bootstrap

From repo root:

```powershell
.\scripts\setup-groksearch-local.ps1 -PrintEnvTemplate
```

What it does:

- runs `uv sync --project apps/groksearch-bridge`
- installs upstream `GuDaStudio/GrokSearch@grok-with-tavily` into the bridge virtual environment
- validates that `grok-search` can be found
- validates required auth keys

If you only want to re-check current setup:

```powershell
.\scripts\setup-groksearch-local.ps1 -CheckOnly
```

If you want to force reinstall upstream GrokSearch:

```powershell
.\scripts\setup-groksearch-local.ps1 -ForceReinstall
```

## Root `.env`

The project already reads `E:\travel\.env` for backend variables. Add a block like this:

```env
TRAVELMIND_GROKSEARCH_COMMAND=grok-search
TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY=change-this-bridge-key
TRAVELMIND_GROKSEARCH_BRIDGE_BASE_URL=http://127.0.0.1:8085/mcp
TRAVELMIND_GROKSEARCH_BRIDGE_TIMEOUT_SECONDS=30
TRAVELMIND_SEARCH_SERVICE_PROVIDER=groksearch
TRAVELMIND_SEARCH_SERVICE_TRANSPORT=mcp

GUDA_API_KEY=
GROK_API_KEY=
GROK_API_URL=
GROK_MODEL=Web/grok-chat-fast
GROK_WIRE_API=chat_completions

TAVILY_ENABLED=true
TAVILY_API_KEY=
TAVILY_API_URL=
FIRECRAWL_API_KEY=
FIRECRAWL_API_URL=
```

At least one of these must exist:

- `GUDA_API_KEY`
- `GROK_API_KEY`

## Start Services

Bridge:

```powershell
uv run --project apps/groksearch-bridge uvicorn travelmind_groksearch_bridge.main:app --host 127.0.0.1 --port 8085
```

API:

```powershell
uv run --project apps/api uvicorn travelmind_api.main:app --host 127.0.0.1 --port 8000
```

Worker:

```powershell
uv run --project apps/worker python -m travelmind_worker.worker
```

## Notes

- The bootstrap script installs upstream GrokSearch into the bridge virtual environment, not the system Python.
- If your local shell cannot resolve `grok-search`, keep using the bridge project virtual environment via `uv run --project apps/groksearch-bridge ...`.
