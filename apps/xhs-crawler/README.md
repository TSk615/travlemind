# TravelMind XHS Browser Node

This service exposes internal Xiaohongshu browser-node endpoints for TravelMind.

## What it exposes

- `GET /health`
- `POST /internal/xhs/bind/start`
- `GET /internal/xhs/bind/{bind_id}`
- `POST /internal/xhs/session/search`
- `DELETE /internal/xhs/session/{user_id}`

## Local run

```powershell
$env:TRAVELMIND_XHS_NODE_BINARY='node'
$env:TRAVELMIND_XHS_OPENCLI_BINARY='opencli'
uv run --project apps/xhs-crawler uvicorn travelmind_xhs_crawler.main:app --host 127.0.0.1 --port 8090 --app-dir apps/xhs-crawler/src
```

## Adapter contract

TravelMind expects its OpenCLI adapter or fork to read these environment variables:

- `TRAVELMIND_XHS_BIND_ID`
- `TRAVELMIND_XHS_USER_ID`
- `TRAVELMIND_XHS_QUERY`
- `TRAVELMIND_XHS_NOTE_REF`
- `TRAVELMIND_XHS_DESTINATION`
- `TRAVELMIND_XHS_LIMIT_PER_QUERY`
- `TRAVELMIND_XHS_SESSION_FILE`
- `TRAVELMIND_XHS_RUN_DIR`

Each command should print one JSON payload to stdout.

## Notes

- This service no longer wraps MediaCrawler.
- The browser node is intended for internal or research use only.
