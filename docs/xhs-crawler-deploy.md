# Xiaohongshu Browser Node Deployment

This project now treats Xiaohongshu support as a separate internal browser node named `xhs-crawler`.

## Runtime shape

- The API stays on the normal application server.
- `xhs-crawler` runs as a dedicated browser-capable node.
- Users bind their own Xiaohongshu account once, then the API reuses that user-specific session.
- If the session is missing or expired, API search falls back to non-XHS sources and asks the user to rebind.

## Required settings

Set these values before enabling Xiaohongshu in API:

- `TRAVELMIND_XHS_CRAWLER_ENABLED=true`
- `TRAVELMIND_XHS_CRAWLER_BASE_URL=http://xhs-crawler:8090`
- `TRAVELMIND_XHS_SESSION_SECRET=<long random secret>`
- `TRAVELMIND_XHS_NODE_BINARY=node`
- `TRAVELMIND_XHS_OPENCLI_BINARY=opencli`

## Internal interfaces

The API talks to the browser node over these internal endpoints:

- `POST /internal/xhs/bind/start`
- `GET /internal/xhs/bind/{bind_id}`
- `POST /internal/xhs/session/search`
- `DELETE /internal/xhs/session/{user_id}`

## Browser node expectations

- Node.js `>= 21`
- OpenCLI installed on the browser node
- A TravelMind-maintained Xiaohongshu adapter or fork that can:
  - emit bind QR metadata
  - emit authorized session payloads
  - restore a user session from `TRAVELMIND_XHS_SESSION_FILE`
  - return search and note JSON results

## Notes

- The service is intended for internal or research use only.
- Results are still cached on the API side via `TRAVELMIND_XHS_CACHE_TTL_SECONDS`.
- If the browser node is unavailable, itinerary generation and search continue with non-XHS sources.
