# API Overview

All endpoints return:

```json
{
  "data": {},
  "error": null,
  "meta": {}
}
```

## Auth

- `POST /api/v1/auth/register`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/me`

## Account

- `GET /api/v1/account/xhs/status`
- `POST /api/v1/account/xhs/bind`
- `GET /api/v1/account/xhs/bind/{bind_id}`
- `DELETE /api/v1/account/xhs/bind`

## Trips

- `POST /api/v1/trips`
- `GET /api/v1/trips`
- `GET /api/v1/trips/{id}`
- `PATCH /api/v1/trips/{id}`
- `DELETE /api/v1/trips/{id}`
- `PUT /api/v1/trips/{id}/itinerary`
- `POST /api/v1/trips/intake/chat`
- `POST /api/v1/trips/{id}/generate`
- `POST /api/v1/trips/{id}/refine`
- `POST /api/v1/trips/{id}/images/enrich`

## Search / Export / Jobs

- `POST /api/v1/search`
- `POST /api/v1/exports`
- `POST /api/v1/exports/pdf`
- `GET /api/v1/jobs/{id}`
- `GET /api/v1/jobs/{id}/stream`

## Runtime Settings

- `GET /api/v1/settings/llm`
- `PUT /api/v1/settings/llm`

## LLM Utilities

- `POST /api/v1/llm/proxy`
- `POST /api/v1/llm/models`
- `POST /api/v1/llm/test`
- `POST /api/v1/llm/search-proxy`
- `POST /api/v1/llm/search-images-proxy`
- `POST /api/v1/llm/tavily-images-proxy`
- `POST /api/v1/llm/xhs-images-proxy`

## Images

- `POST /api/v1/images/prompts/compose`
- `POST /api/v1/images/generate`
- `GET /api/v1/images`
- `GET /api/v1/images/feed`
- `GET /api/v1/images/prompt-trends`
- `GET /api/v1/images/{generation_id}`
- `PATCH /api/v1/images/{generation_id}`
- `POST /api/v1/images/{generation_id}/remix`

## Community

- `GET /api/v1/posts`
- `GET /api/v1/posts/{post_id}`
- `POST /api/v1/posts`
- `PATCH /api/v1/posts/{post_id}`
- `POST /api/v1/posts/{post_id}/refresh-from-trip`
- `DELETE /api/v1/posts/{post_id}`
