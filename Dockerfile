FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Install uv (fast Python package manager)
RUN pip install --no-cache-dir uv

# Copy project metadata first for better layer caching
COPY pyproject.toml ./
# uv.lock will be present after the first `uv lock` / `uv sync` run.
COPY uv.loc[k] ./

# Sync runtime dependencies
RUN uv sync --no-dev

# Copy application source
COPY app ./app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
