# syntax=docker/dockerfile:1.7
# Multi-stage, non-root, healthcheck-capable (Appendix D.7).

# ---------------------------------------------------------------------------
FROM python:3.13-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ---------------------------------------------------------------------------
FROM base AS deps
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /wheels
COPY requirements.txt requirements-dev.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements-dev.txt

# ---------------------------------------------------------------------------
FROM base AS runtime
RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 curl \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --gid 10001 app \
 && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY --from=deps /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app

WORKDIR /app
COPY --chown=app:app . /app
RUN chmod +x /app/scripts/*.sh 2>/dev/null || true

USER app
EXPOSE 8080

# ⚠ The path includes the API prefix. Moving routers under /api/v1 breaks every
# hardcoded path that wasn't grepped for -- and a healthcheck is the one nobody
# thinks to grep, because a failing probe looks like a sick app rather than a
# stale URL (Appendix D.2).
#
# Services without an HTTP port (workers) must disable this in compose --
# an inherited healthcheck on a worker fails forever (Appendix D.7 trap).
HEALTHCHECK --interval=30s --timeout=5s --start-period=25s --retries=3 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://localhost:8080/api/v1/health/live').read()" || exit 1

CMD ["python", "-m", "app.entrypoints.api"]
