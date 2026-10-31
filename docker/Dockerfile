# syntax=docker/dockerfile:1

# Every stage runs on the same Python image: the virtual environment made in the build stage
# only works with the Python it was made for (its packages are in lib/python3.X). The image
# appears in each FROM below, so Dependabot moves them together. A new Python version comes
# with .python-version, which the tests run on.
#
# uv comes from its own image, at a fixed version.
FROM ghcr.io/astral-sh/uv:0.13.1 AS uv


# Build stage: install the locked dependencies and the app into a virtual environment.
FROM python:3.13-slim-trixie AS build

COPY --from=uv /uv /usr/local/bin/uv

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
# The translations are read compiled (.mo); the running container cannot write them.
RUN .venv/bin/python -c "from sleeve_shelf.web.language import compile_catalogues; compile_catalogues()"


# Docs stage: the documentation site, built with Zensical, which the app serves as its help.
FROM python:3.13-slim-trixie AS docs

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Only the tools the documentation needs (the dev group), not the app itself.
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --only-group dev --no-install-project

COPY docs-site ./docs-site
RUN cd docs-site && uv run --no-sync python -m zensical build --strict


# Runtime stage: only Python, the virtual environment, and the built help.
FROM python:3.13-slim-trixie

ARG APP_VERSION=dev

ENV SLEEVE_SHELF_VERSION=${APP_VERSION} \
    SLEEVE_SHELF_DATA_DIR=/data \
    SLEEVE_SHELF_HELP_DIR=/app/help \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1

# pip is not needed to run the app (uv installed everything in the build stage), and the
# packages it carries along would only be found by the image scan.
RUN python -m pip uninstall --yes pip \
    && useradd --system --uid 1000 --create-home sleeve \
    && mkdir /data \
    && chown sleeve /data

COPY --from=build /app/.venv /app/.venv
COPY --from=docs /app/docs-site/site /app/help

# The build fails here, not the container at its start, when the environment does not fit
# this Python.
RUN python -c "import sleeve_shelf.web.app, waitress"

USER sleeve

# The collection (JSON files) lives here; mount a volume to keep it.
VOLUME /data
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/setup/', timeout=3)"]

CMD ["waitress-serve", "--host=0.0.0.0", "--port=5000", "--call", "sleeve_shelf.web.app:create_app"]
