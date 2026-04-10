FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Non-root user for security
RUN useradd --create-home --uid 10001 app
WORKDIR /app

# Copy dependency manifest first — changes here bust the cache, source changes do not
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# Copy application source and migration files
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Persist auth DB and user-supplied SQLite DBs (dev only) on a volume
RUN mkdir -p /var/lib/mcp-db-agent/user-dbs && \
    chown -R app:app /app /var/lib/mcp-db-agent

USER app

EXPOSE 8000

ENV ENVIRONMENT=production
ENV TRANSPORT=streamable-http
ENV TRUSTED_PROXY_IPS=127.0.0.1

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=3).status==200 else 1)"

# Production: 4 workers, proxy headers.
# TRUSTED_PROXY_IPS is read at runtime via shell expansion — never hardcode "*".
# Override at deploy time: docker run -e TRUSTED_PROXY_IPS=10.0.0.0/8 ...
CMD ["sh", "-c", "exec uv run uvicorn src.app:app \
     --host 0.0.0.0 --port 8000 \
     --workers 4 \
     --proxy-headers --forwarded-allow-ips \"${TRUSTED_PROXY_IPS}\""]

# For stdio single-user mode:
# docker run -e TRANSPORT=stdio --entrypoint uv ... run src/server.py
