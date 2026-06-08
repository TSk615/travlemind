# TravelMind AI

TravelMind AI is the MVP monorepo for trip planning, itinerary generation, compliant search, and PDF export. The current repository contains:

- `apps/web`: Vue 3 + Vite SPA
- `apps/api`: FastAPI backend
- `apps/worker`: ARQ worker
- `apps/groksearch-bridge`: HTTP MCP bridge for upstream GrokSearch
- `packages/*`: shared frontend contracts, UI tokens, and config helpers
- `docs`: architecture and product notes
- `infra`: Docker, Compose, nginx, and environment templates

The product brief targets a broader hybrid-stack monorepo. This repo currently runs the MVP loop on a Vue/Vite web app plus FastAPI/worker backend, and the startup instructions below match that current implementation.

## Prerequisites

- Node.js 20+
- Python 3.11+
- `uv`
- Docker Desktop or Docker Engine with the Compose plugin for container runs

## Local Development

The fastest local closed loop uses the API in `inline` mode and the `stub` orchestrator. That path does not require Redis, Postgres, or `helloagents`.

### 1. Install frontend dependencies

```powershell
npm install
```

### 2. Start the API

The API works with defaults. If you need overrides, copy keys from [infra/.env.example](E:/travel/infra/.env.example) into `E:\travel\.env`.

```powershell
$env:TRAVELMIND_AGENT_PROVIDER="stub"
$env:TRAVELMIND_QUEUE_MODE="inline"
uv sync --frozen --project apps/api
uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port 8000
```

### 3. Start the web app

```powershell
$env:VITE_API_BASE_URL="http://127.0.0.1:8000"
npm run dev:web
```

Open `http://127.0.0.1:5173`.

### 4. Optional: start the worker for real async jobs

Use this only when you want ARQ-backed async execution instead of inline jobs.

```powershell
docker compose -f infra/docker-compose.yml up redis -d
$env:TRAVELMIND_AGENT_PROVIDER="stub"
$env:TRAVELMIND_QUEUE_MODE="arq"
$env:TRAVELMIND_REDIS_URL="redis://127.0.0.1:6379/0"
uv sync --project apps/worker
uv run --project apps/worker python -m travelmind_worker.worker
```

If you switch the API to ARQ mode, start it with the same Redis URL:

```powershell
$env:TRAVELMIND_QUEUE_MODE="arq"
$env:TRAVELMIND_REDIS_URL="redis://127.0.0.1:6379/0"
uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port 8000
```

## Service Commands

### Web

```powershell
npm run dev:web
npm run build:web
npm run preview:web
```

### API

```powershell
uv sync --frozen --project apps/api
uv run --project apps/api pytest apps/api/tests
uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port 8000
```

### Worker

```powershell
uv sync --project apps/worker
uv run --project apps/worker python -m travelmind_worker.worker
```

### GrokSearch Bridge Local Setup

To prepare a non-Docker local GrokSearch bridge environment:

```powershell
.\scripts\setup-groksearch-local.ps1 -PrintEnvTemplate
```

To re-check the current local setup without reinstalling upstream GrokSearch:

```powershell
.\scripts\setup-groksearch-local.ps1 -CheckOnly
```

## Docker and Compose

### Build individual images

Run these from `E:\travel`.

```powershell
docker build --build-arg VITE_API_BASE_URL=http://localhost:8000 -f apps/web/Dockerfile -t travelmind-web .
docker build -f apps/api/Dockerfile -t travelmind-api .
docker build -f apps/worker/Dockerfile -t travelmind-worker .
docker build -f apps/groksearch-bridge/Dockerfile -t travelmind-groksearch-bridge .
```

### Run the full container stack

The Compose stack builds `web`, `api`, and `worker`, shares a writable `storage` volume for SQLite and PDF exports, and starts Redis for ARQ. By default it uses SQLite inside the shared volume so the MVP can run without changing Python dependencies.

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml up --build
```

Then open:

- Web: `http://localhost:3000`
- API: `http://localhost:8000`
- API health: `http://localhost:8000/health`
- GrokSearch bridge: `http://localhost:8085/mcp`

To stop and remove containers:

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml down
```

### Optional Postgres profile

Compose includes a `postgres` service as an opt-in profile:

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml --profile postgres up postgres -d
```

This is only a deployment placeholder right now. The current Python dependencies in `apps/api` and `apps/worker` do not yet include a PostgreSQL driver, so switching `TRAVELMIND_DATABASE_URL` from SQLite to Postgres will require that dependency to be added in a later business-code change.

## CI Baseline

GitHub Actions currently validates four things:

- web workspace install and production build
- API dependency sync plus pytest
- worker dependency sync plus import smoke test
- Dockerfile builds for `web`, `api`, and `worker`, plus Compose config validation

See [ci.yml](E:/travel/.github/workflows/ci.yml).

## Environment Notes

[infra/.env.example](E:/travel/infra/.env.example) is the baseline template for Docker and for local overrides. Important variables:

- `TRAVELMIND_AGENT_PROVIDER=stub` is the safe default for local development and CI
- `TRAVELMIND_QUEUE_MODE=inline` is the simplest direct-run mode
- `TRAVELMIND_QUEUE_MODE=arq` requires Redis and the worker
- `VITE_API_BASE_URL` is baked into the web image at build time
- `TRAVELMIND_CORS_ORIGINS` must include the browser origin you use locally
- `TRAVELMIND_SEARCH_SERVICE_PROVIDER=groksearch` switches backend search defaults to the bundled GrokSearch bridge
- `TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY` protects the bridge MCP endpoint

For GrokSearch deployment details, see [groksearch-bridge-deploy.md](E:/travel/docs/groksearch-bridge-deploy.md).
For non-Docker local setup, see [groksearch-local-setup.md](E:/travel/docs/groksearch-local-setup.md).

## HelloAgents PoC Notice

`helloagents` is only allowed here behind the internal orchestrator adapter boundary as a PoC integration target. Do not tag, market, or ship this repository as a commercial release while the `HelloAgentsOrchestrator` adapter remains in place, unless separate licensing review and replacement work have been completed first.

