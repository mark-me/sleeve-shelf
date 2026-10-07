# syntax=docker/dockerfile:1

# Build stage: install the locked dependencies and the app into a virtual environment.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS build

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, so this layer is reused while only the source changes.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable


# Runtime stage: only Python and the virtual environment.
FROM python:3.13-slim-bookworm

ARG APP_VERSION=dev

ENV SLEEVE_SHELF_VERSION=${APP_VERSION} \
    SLEEVE_SHELF_DATA_DIR=/data \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

RUN useradd --system --uid 1000 --create-home sleeve \
    && mkdir /data \
    && chown sleeve /data

COPY --from=build /app/.venv /app/.venv

USER sleeve

# The collection (JSON files) lives here; mount a volume to keep it.
VOLUME /data
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/setup/', timeout=3)"]

CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--call", "sleeve_shelf:create_app"]
