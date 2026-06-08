# Architecture

## MVP shape

- Vue SPA (`apps/web`) talks directly to the FastAPI backend.
- FastAPI owns auth, account bindings, trips, search, image generation, community posts, runtime settings, job lifecycle, and export endpoints.
- ARQ worker consumes asynchronous jobs for itinerary generation, refinement, image enrichment, image generation, and PDF export.
- PostgreSQL is the production target. SQLite is supported locally through the same SQLAlchemy models.
- Redis backs the worker queue in production. Inline execution is available for local development and tests.

## AI orchestration

- `AgentOrchestrator` is the internal contract for planning, source summarization, and export drafting.
- `StubOrchestrator` is the baseline implementation for tests and local smoke runs.
- `HelloAgentsOrchestrator` is a PoC adapter behind the internal contract. It can use configured LLM endpoints plus configured search grounding, but should not be treated as a production/commercial dependency without licensing review.
- Runtime LLM settings are stored per user and exposed through `/api/v1/settings/llm`. The current client layer supports OpenAI Responses, OpenAI-compatible Chat Completions, Gemini, Claude, NewAPI, and NeiAPI-style endpoints.

## Search

- Search combines seeded official sources, user-supplied links, configured remote search, and optional Xiaohongshu social-source enrichment.
- Configured remote search currently supports GrokSearch through the MCP bridge and Tavily through direct API transport.
- Search results always return a `ScoreBreakdown` structure with trust, quality, freshness, ad, and final scores. Ranking is still heuristic and should be reviewed before production tuning.

## Frontend

- The active Vite entrypoint is `apps/web/src/main.ts`.
- Shared UI tokens live in `apps/web/src/styles/tokens.css` and `packages/ui/src/styles.css`.
- Legacy JavaScript files under `apps/web/src/**/*.js` are ignored as generated or historical artifacts and are not part of the current TypeScript build path.
