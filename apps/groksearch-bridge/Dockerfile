FROM python:3.11-slim AS build
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_EXTRA_INDEX_URL=
ARG PIP_DEFAULT_TIMEOUT=120
ARG GROKSEARCH_GIT_URL=https://github.com/GuDaStudio/GrokSearch
ARG GROKSEARCH_REF=grok-with-tavily
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy
ENV PIP_INDEX_URL=${PIP_INDEX_URL}
ENV PIP_EXTRA_INDEX_URL=${PIP_EXTRA_INDEX_URL}
ENV PIP_DEFAULT_TIMEOUT=${PIP_DEFAULT_TIMEOUT}
ENV PIP_RETRIES=10

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --default-timeout=${PIP_DEFAULT_TIMEOUT} uv

COPY apps/groksearch-bridge/pyproject.toml /app/apps/groksearch-bridge/pyproject.toml
RUN uv sync --project /app/apps/groksearch-bridge --no-install-project

COPY apps/groksearch-bridge /app/apps/groksearch-bridge
RUN uv sync --project /app/apps/groksearch-bridge

RUN /app/apps/groksearch-bridge/.venv/bin/pip install --no-cache-dir "git+${GROKSEARCH_GIT_URL}@${GROKSEARCH_REF}"

FROM python:3.11-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/apps/groksearch-bridge/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/apps/groksearch-bridge/src"
ENV TRAVELMIND_GROKSEARCH_COMMAND="grok-search"

WORKDIR /app

COPY --from=build /app/apps/groksearch-bridge /app/apps/groksearch-bridge

EXPOSE 8085

CMD ["uvicorn", "travelmind_groksearch_bridge.main:app", "--host", "0.0.0.0", "--port", "8085"]
