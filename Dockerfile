FROM python:3.12-slim

# Install uv via the official distroless image (no curl required)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency manifest first — changes here bust the cache, source changes do not
COPY pyproject.toml uv.lock ./

# Install production dependencies only into the project-local .venv
RUN uv sync --no-dev --frozen

# Copy application source
COPY src/ ./src/

EXPOSE 8000

# Default to HTTP transport; override with -e TRANSPORT=stdio for local/stdio use
ENV TRANSPORT=streamable-http

CMD ["uv", "run", "src/server.py"]
