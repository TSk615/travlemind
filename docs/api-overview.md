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
- `POST /api/v1/auth/logout`
- `GET /api/v1/me`

## Trips

- `POST /api/v1/trips`
- `GET /api/v1/trips`
- `GET /api/v1/trips/{id}`
- `PATCH /api/v1/trips/{id}`
- `POST /api/v1/trips/{id}/generate`

## Search / Export / Jobs

- `POST /api/v1/search`
- `POST /api/v1/exports/pdf`
- `GET /api/v1/jobs/{id}`
- `GET /api/v1/jobs/{id}/stream`
