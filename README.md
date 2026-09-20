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

The fastest local closed loop uses the API in `inline` mode and the `stub` orchestrator. That path does not require Redis or Postgres.

### One-click start and stop (Windows)

From the repository root, start the web app, API, and GrokSearch bridge in the background:

```powershell
.\start.cmd
```

Run this command from a regular PowerShell or Windows Terminal window. The launcher intentionally refuses to start inside a network-disabled Codex sandbox because child services would be unable to reach external model providers.

Logs and process state are written under `.tmp\local-dev`. Stop every process started by the script with:

```powershell
.\stop.cmd
```

The default mode uses inline jobs and the stub agent, so Redis and the worker are not started. For ARQ mode, start Redis first and then run `start.cmd -ArqMode`. Other supported switches include `-SkipBridge`, `-SkipApi`, `-SkipWorker`, `-SkipWeb`, `-LangGraph`, and custom `-BridgePort`, `-ApiPort`, or `-WebPort` values.

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

The Compose stack builds `web`, `api`, and `worker`, starts PostgreSQL for application data and shared LangGraph checkpoints, and starts Redis for ARQ. API and worker receive the same explicit PostgreSQL checkpoint URL so resumable jobs work across worker processes. The writable `storage` volume remains available for generated files such as PDF exports.

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

### Start only PostgreSQL

To start only the managed PostgreSQL service for direct local API/worker runs:

```powershell
docker compose --env-file infra/.env.example -f infra/docker-compose.yml up postgres -d
```

Both Python applications include the Psycopg driver. Application tables use the SQLAlchemy URL in `TRAVELMIND_COMPOSE_DATABASE_URL`; LangGraph uses the Psycopg URL in `TRAVELMIND_COMPOSE_WORKFLOW_CHECKPOINT_URL`.

## CI Baseline

GitHub Actions currently validates:

- whitespace and Python compilation
- web unit tests, production build, and Chromium E2E
- API dependency sync plus the full pytest suite against a real PostgreSQL 16 service, including Alembic cycling and checkpoint recovery
- worker dependency sync plus import smoke test
- Dockerfile builds for `web`, `api`, and `worker`, plus Compose config validation

See [ci.yml](E:/travel/.github/workflows/ci.yml).

## Environment Notes

[infra/.env.example](E:/travel/infra/.env.example) is the baseline template for Docker and for local overrides. Important variables:

- `TRAVELMIND_AGENT_PROVIDER=stub` is the safe default for local development and CI
- `TRAVELMIND_QUEUE_MODE=inline` is the simplest direct-run mode
- `TRAVELMIND_QUEUE_MODE=arq` requires Redis and the worker
- multi-worker LangGraph deployments must give API and worker the same PostgreSQL `TRAVELMIND_WORKFLOW_CHECKPOINT_URL`; Compose does this explicitly
- `VITE_API_BASE_URL` is baked into the web image at build time
- `TRAVELMIND_CORS_ORIGINS` must include the browser origin you use locally
- `TRAVELMIND_SEARCH_SERVICE_PROVIDER=groksearch` switches backend search defaults to the bundled GrokSearch bridge
- `TRAVELMIND_GROKSEARCH_BRIDGE_API_KEY` protects the bridge MCP endpoint

For GrokSearch deployment details, see [groksearch-bridge-deploy.md](E:/travel/docs/groksearch-bridge-deploy.md).
For non-Docker local setup, see [groksearch-local-setup.md](E:/travel/docs/groksearch-local-setup.md).

## Workflow runtime

Generation and refinement use the internal orchestrator contract. `langgraph` is the durable multi-role implementation; `standard` is the single-model fallback and `stub` supports deterministic local development. The former HelloAgents package is no longer a runtime dependency. Historical traces that name it remain readable.

