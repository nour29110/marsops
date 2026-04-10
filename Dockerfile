# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build dependencies with uv ----------
FROM python:3.11-slim-bookworm AS builder

# System deps for rasterio + scipy wheels (GDAL is NOT needed when using prebuilt rasterio wheels,
# but we keep build-essential for any source builds that sneak through)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy only files needed to resolve deps first (maximizes layer caching)
COPY pyproject.toml uv.lock README.md ./
COPY src ./src

# Install into a venv at /app/.venv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

RUN uv sync --frozen --no-dev

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim-bookworm AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libexpat1 \
    libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash marsops

WORKDIR /app

# Copy venv and source (as root, with chown)
COPY --from=builder --chown=marsops:marsops /app/.venv /app/.venv
COPY --from=builder --chown=marsops:marsops /app/src /app/src
COPY --from=builder --chown=marsops:marsops /app/pyproject.toml /app/pyproject.toml

# Create the data cache dir AS ROOT, then chown it to marsops (must run before USER marsops)
RUN mkdir -p /app/data/raw && chown -R marsops:marsops /app/data

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8000

# Switch user AFTER creating the dir (non-root cannot chown reliably)
USER marsops

EXPOSE 8000

# Start the FastAPI app. `marsops-web` is the console script installed by the project.
CMD ["sh", "-c", "marsops-web --host 0.0.0.0 --port ${PORT}"]
