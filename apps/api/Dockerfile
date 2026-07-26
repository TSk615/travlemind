FROM python:3.11-slim AS build
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_DEFAULT_TIMEOUT=120
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}
ENV PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}
ENV PIP_RETRIES=10

WORKDIR /app

RUN pip install --no-cache-dir --default-timeout=${PIP_DEFAULT_TIMEOUT} uv

COPY apps/api/pyproject.toml /app/apps/api/pyproject.toml
COPY apps/api/uv.lock /app/apps/api/uv.lock

RUN uv sync --frozen --no-dev --project /app/apps/api --no-install-project

COPY apps/api /app/apps/api

RUN uv sync --frozen --no-dev --project /app/apps/api

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/apps/api/.venv/bin:${PATH}"

WORKDIR /app

COPY --from=build /app/apps/api /app/apps/api

RUN mkdir -p /app/storage/exports

EXPOSE 8000

CMD ["uvicorn", "travelmind_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
