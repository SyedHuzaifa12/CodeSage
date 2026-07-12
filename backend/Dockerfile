# syntax=docker/dockerfile:1

# Pinned to a stable, widely-supported Python release rather than the newest
# interpreter, since upcoming sprints add compiled dependencies (Tree-sitter
# bindings, psycopg2, sentence-transformers) that need mature wheel support.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# git is required at runtime by GitPython (it shells out to the real
# git binary) — the slim base image doesn't include it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

# Installed before the app code so this layer only rebuilds when
# dependencies change, not on every source edit.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data/repositories \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
