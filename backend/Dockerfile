# syntax=docker/dockerfile:1
# =============================================================================
# Q-Lab — Backend (FastAPI) production image
# =============================================================================
# Build context is the repo ROOT (see docker-compose.yml: context: .), so all
# COPY paths below are relative to the project root.
#
#   $ docker build -f backend/Dockerfile -t qlab-backend .
#   $ docker compose up backend
#
# The .env is provided at RUNTIME (compose `env_file: .env`); no secrets are
# baked into the image.
#
# NOTE ON IMAGE SIZE: pyproject.toml declares a single `dependencies` list that
# mixes backend runtime deps with research/notebook deps (jupyterlab,
# matplotlib, seaborn, ipykernel, optuna, scikit-learn, ...). There is no
# backend-only extra to target, and the backend imports `research.*` modules at
# runtime (research.factors / research.backtest / research.universe), so the
# full set is installed. => the image is intentionally heavy.
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1 — builder: resolve + install all deps into an isolated virtualenv.
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# build-essential is insurance for any dep that ships only an sdist; it stays in
# the (discarded) builder stage and never reaches the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

# Copy only the dependency manifest first for better layer caching.
COPY pyproject.toml ./

# Install DEPENDENCIES ONLY (not the project package). Installing `.` would try
# to build the `qlab` package, but the repo is a flat multi-package layout with
# no [build-system] table, so `-r pyproject.toml` (deps only) is used instead.
# The application code itself is added to the image via COPY + PYTHONPATH below.
RUN uv venv "$VIRTUAL_ENV" \
    && uv pip install -r pyproject.toml

# -----------------------------------------------------------------------------
# Stage 2 — runtime: slim image with just the venv + application source.
# -----------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Seoul \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

# tzdata: needed so TZ=Asia/Seoul and ZoneInfo("Asia/Seoul") (schedulers) resolve.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# Bring in the pre-built virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app

# Application source. `app/` (Flutter), tests, notebooks, reports, and data are
# excluded via .dockerignore. `data/` is bind-mounted at runtime, not copied.
COPY backend/ ./backend/
COPY shared/ ./shared/
COPY research/ ./research/

# Run as a non-root user; give it ownership so runtime dirs (logs) are writable.
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /app/data /app/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# /health returns 200 (ok) or 503 (degraded). urllib raises on 503 -> unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/health', timeout=4).status == 200 else 1)"]

# Production shape: NO --reload. .env supplied at runtime via compose env_file.
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
