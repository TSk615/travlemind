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

COPY apps/worker/pyproject.toml /app/apps/worker/pyproject.toml

RUN uv sync --project /app/apps/worker --no-install-project

COPY apps/api /app/apps/api
COPY apps/worker /app/apps/worker

RUN uv sync --project /app/apps/worker

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/apps/worker/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/apps/worker/src:/app/apps/api/src"

WORKDIR /app

COPY --from=build /app/apps/api /app/apps/api
COPY --from=build /app/apps/worker /app/apps/worker

RUN mkdir -p /app/storage/exports

CMD ["python", "-m", "travelmind_worker.worker"]
