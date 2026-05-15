# Architecture

## MVP shape

- Vue SPA (`apps/web`) talks directly to the FastAPI backend.
- FastAPI owns auth, trips, search, job lifecycle, and export endpoints.
- ARQ worker consumes asynchronous jobs for itinerary generation and PDF export.
- PostgreSQL is the production target. SQLite is supported locally through the same SQLAlchemy models.
- Redis backs the worker queue in production. Inline execution is available for local development and tests.

## AI orchestration

- `AgentOrchestrator` is the internal contract for planning, source summarization, and export drafting.
- `HelloAgentsOrchestrator` is a PoC adapter with a deterministic fallback so local development does not require the third-party dependency.
- `StubOrchestrator` is the baseline implementation for tests and local smoke runs.

## Search

- MVP search only combines seeded official sources and user-supplied links.
- Search results always return a `ScoreBreakdown` structure, but ad detection and ranking are placeholders during the MVP.
