# ── Stage 1: Build frontend ────────────────────────────────────────────────
FROM node:20-slim AS frontend
WORKDIR /build
COPY webapp/frontend/package.json webapp/frontend/package-lock.json* ./
RUN npm ci --ignore-scripts 2>/dev/null || npm install --ignore-scripts
COPY webapp/frontend/ ./
RUN npm run build

# ── Stage 2: Runtime ──────────────────────────────────────────────────────
FROM python:3.12-slim

# ffmpeg (аудио) + curl (deno) — build-essential/cmake убраны (ML на Supabase)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl unzip \
    && rm -rf /var/lib/apt/lists/*

# deno (JS-рантайм для yt-dlp signature solving) — pinned version + SHA256 verify
ENV DENO_VERSION=2.7.11
RUN set -eux; \
    curl -fsSL -o /tmp/deno.zip \
      "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip"; \
    curl -fsSL -o /tmp/deno.zip.sha256sum \
      "https://github.com/denoland/deno/releases/download/v${DENO_VERSION}/deno-x86_64-unknown-linux-gnu.zip.sha256sum"; \
    cd /tmp && sha256sum -c deno.zip.sha256sum; \
    unzip -o /tmp/deno.zip -d /usr/local/bin; \
    chmod +x /usr/local/bin/deno; \
    rm /tmp/deno.zip /tmp/deno.zip.sha256sum; \
    deno --version

# Remove curl/unzip no longer needed at runtime
RUN apt-get purge -y --auto-remove curl unzip \
    || true

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ bot/
COPY recommender/ recommender/
COPY mixer/ mixer/
COPY webapp/ webapp/
COPY parser/ parser/
COPY streamer/ streamer/
COPY main.py alembic.ini ./
COPY migrations/ migrations/

# Copy built frontend (Node.js not needed at runtime)
COPY --from=frontend /build/dist webapp/frontend/dist

RUN mkdir -p /app/data /app/downloads /app/logs

# Non-root user
RUN groupadd -r appuser && useradd -r -g appuser -d /app appuser \
    && chown -R appuser:appuser /app
USER appuser

CMD ["python", "-m", "bot.main"]
