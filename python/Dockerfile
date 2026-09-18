FROM ghcr.io/astral-sh/uv:0.5.29 AS uv

FROM python:3.12.8-slim-bookworm AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

COPY --from=uv /uv /uvx /bin/

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential default-libmysqlclient-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . ./
RUN uv sync --frozen --no-dev

FROM python:3.12.8-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    HF_HOME=/data/models

RUN apt-get update \
    && apt-get install --no-install-recommends -y libmariadb3 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 sentinel \
    && useradd --system --uid 10001 --gid sentinel --home-dir /app --shell /usr/sbin/nologin sentinel \
    && mkdir -p /app /data/chroma /data/models \
    && chown -R sentinel:sentinel /app /data

WORKDIR /app
COPY --from=build --chown=sentinel:sentinel /app /app

USER sentinel
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
