FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV UV_LINK_MODE=copy

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

COPY apps/xhs-crawler /app/apps/xhs-crawler
RUN uv sync --project /app/apps/xhs-crawler

ENV PATH="/app/apps/xhs-crawler/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/apps/xhs-crawler/src"

EXPOSE 8090

CMD ["uvicorn", "travelmind_xhs_crawler.main:app", "--host", "0.0.0.0", "--port", "8090"]
