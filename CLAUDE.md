# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

An MCP (Model Context Protocol) server that exposes any PostgreSQL or SQLite database as a natural-language queryable endpoint. Any MCP client (Claude Desktop, Cursor, VS Code Copilot) can connect and ask questions in plain English. The server introspects the schema, generates SQL via an LLM, validates it for safety, executes it, and returns structured JSON — with a self-correction retry loop if execution fails.

**Two deployment modes:**
- **Stdio / single-user** (`uv run src/server.py`): local dev, Claude Desktop, VS Code Copilot.
- **Hosted / multi-tenant** (`uvicorn src.app:app`): multiple users register their own database, receive an API key, and connect to a shared HTTP endpoint.

## Commands

**Package manager: `uv` only** — do not use pip or Poetry.

```bash
# Install all dependencies (including dev)
uv sync

# Run all unit tests (no LLM calls, no DB required)
uv run pytest -m "not integration"

# Run a single test file
uv run pytest tests/test_sql_validator.py

# Run a single test by name
uv run pytest tests/test_sql_executor.py::test_execute_aggregation_count

# Run integration tests (needs API keys in .env and a seeded demo.db)
uv run pytest -m integration

# Lint and format
uv run ruff check .
uv run ruff format .

# Type check
uv run mypy src --ignore-missing-imports

# Run the MCP server (stdio transport for Claude Desktop)
uv run src/server.py

# Run hosted HTTP server (multi-tenant)
uv run uvicorn src.app:app --reload

# Debug with MCP Inspector (requires Node.js)
npx @modelcontextprotocol/inspector uv run src/server.py

# Seed the demo SQLite database
uv run scripts/seed_demo_db.py

# Database migrations (Alembic)
uv run alembic upgrade head          # apply all pending migrations
uv run alembic check                 # verify schema is at head
uv run alembic downgrade -1          # roll back one migration
```

## Architecture

### Stdio mode (single-user, local)

```
MCP Client (Claude Desktop / Cursor / VS Code)
    → FastMCP server (src/server.py)           # tool/resource registration, JSON-RPC
        → _get_pipeline() → PipelineFactory.get_from_settings()
            → SchemaInspector (src/core/)       # SQLAlchemy introspection → schema string
            → SQLGenerator (src/core/)          # schema + question → LLM → raw SQL
            → SQLValidator (src/core/)          # blocks writes, checks table refs, injects LIMIT
            → SQLExecutor (src/core/)           # runs query in thread pool with timeout
            → SelfCorrector (src/core/)         # retry loop: error → LLM fix → re-validate → re-execute
```

### Hosted HTTP mode (multi-tenant)

```
HTTPS (terminated at reverse proxy)
    → uvicorn workers (N)
        → Starlette parent app (src/app.py)     # lifespan, route mounting, middlewares
            ├── Mount("/api", FastAPI)           # REST: register, manage users, health
            │       └── UserStore (auth DB)      # users table, quota, key rotation
            └── Mount("/mcp", FastMCP)           # MCP tools/resources
                    └── ApiKeyMiddleware         # X-API-Key / Bearer → UserConfig ContextVar
                            → _get_pipeline()   # reads ContextVar → PipelineFactory
                                → per-user pipeline (SchemaInspector, SQLGenerator, etc.)
```

### Key components

- **`src/config.py`** — `Settings` (pydantic-settings) loaded from `.env`. Single-user fields now optional (default `""`). Multi-tenant fields: `auth_database_url`, `credential_encryption_keys`, `registration_open`, etc.

- **`src/auth/url_guard.py`** — **Security-critical.** Validates every user-supplied `database_url`. Blocks SSRF, path traversal, private IPs, and DNS rebinding. Called at registration and again inside `PipelineFactory.get()`.

- **`src/auth/crypto.py`** — `CredentialCipher` wraps `MultiFernet`. Encrypts/decrypts database URLs and LLM keys at rest. Supports key rotation via comma-separated `CREDENTIAL_ENCRYPTION_KEYS`.

- **`src/auth/user_store.py`** — SQLAlchemy `User` model + `UserStore` data-access class. `UserConfig` frozen dataclass (in-memory only). Schema managed by Alembic — never calls `create_all`.

- **`src/auth/middleware.py`** — `ApiKeyMiddleware` ASGI class. Reads `X-API-Key` or `Authorization: Bearer`. Caches lookups on `sha256(key)`. Sets `user_config_var` ContextVar for the request lifetime; resets in `finally`.

- **`src/core/pipeline_factory.py`** — `PipelineFactory` caches `PipelineComponents` per user config (TTL 1h, max 100 entries). `_DisposingTTLCache` calls `engine.dispose()` on eviction. `get_from_settings()` is the stdio backward-compat path.

- **`src/core/schema_inspector.py`** — `SchemaInspector` wraps SQLAlchemy `inspect()`. `get_full_schema()` is TTL-cached (default 600 s). `refresh()` busts the cache and re-initialises the inspector.

- **`src/core/sql_validator.py`** — `SQLValidator.validate()` runs 6 checks: single-statement guard, forbidden function scan, forbidden pattern scan (COPY...FROM PROGRAM, ATTACH DATABASE, etc.), DML/DDL block, table existence, LIMIT injection.

- **`src/core/sql_executor.py`** — `SQLExecutor` accepts an injected `ThreadPoolExecutor`. Async; runs SQLAlchemy synchronously in the pool. Exceptions are **not** caught — SelfCorrector handles retries.

- **`src/core/query_log.py`** — Logs every query to `query_history` table. Non-nullable `user_id` (use `"__stdio__"` in single-user mode). UTC-aware timestamps. WAL mode enabled for SQLite.

- **`src/api/app.py`** — FastAPI REST API. Endpoints: `POST /v1/users/register`, `GET/PUT/DELETE /v1/users/me`, `POST /v1/users/me/rotate-key`, `GET /health/live`, `GET /health/ready`. Rate-limited by `slowapi`.

- **`src/app.py`** — Combined ASGI entry point for hosted mode. Starlette parent app with `lifespan` that composes the auth DB, `UserStore`, `PipelineFactory`, and `FastMCP`. All middlewares live on the parent app.

## Configuration

### Stdio / single-user mode

Copy `.env.example` to `.env` and fill in the single-user section:

```env
DATABASE_URL=sqlite:///./demo.db        # or postgresql://user:pass@host/db
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
LLM_PROVIDER=anthropic                  # or "groq" for free-tier development
CLAUDE_MODEL=claude-sonnet-4-6
GROQ_MODEL=llama-3.3-70b-versatile
MAX_QUERY_ROWS=100
QUERY_TIMEOUT_SECONDS=30
MAX_SELF_CORRECTION_RETRIES=3
SHUTDOWN_GRACE_PERIOD_SECONDS=30      # how long to wait for in-flight queries on SIGTERM (G10)
```

### Hosted multi-tenant mode

Additional required settings:

```env
ENVIRONMENT=production
AUTH_DATABASE_URL=postgresql://user:pass@host/mcp_auth
CREDENTIAL_ENCRYPTION_KEYS=<base64-fernet-key>
```

Generate an encryption key:
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

> **Rate-limiter scope.** Both the SlowAPI per-IP limiter on REST endpoints and the
> per-API-key burst limiter on `ask_database` (`MCP_BURST_CAPACITY`) use
> in-process counters. With N uvicorn workers the effective cap is `N × limit`.
> Until a Redis-backed shared store is wired up, run prod with a single worker
> (`uvicorn --workers 1`) or accept the worker-multiplied cap. Tracking: G4 in
> `PRODUCTION_GAPS_PLAN.md`.

### Local Stripe webhook testing

Stripe Cloud cannot reach localhost. To exercise the webhook flow (renewals,
cancellations, `past_due` transitions) in dev, run the Stripe CLI:

```bash
stripe listen --forward-to localhost:8000/api/v1/billing/webhook
```

Copy the `whsec_...` value the CLI prints into `STRIPE_WEBHOOK_SECRET` in
`.env` and restart the backend. The webhook is mounted under the FastAPI
sub-app at `/api/v1/billing/webhook` (the parent Starlette app mounts
`api_app` at `/api` — see `src/app.py`).

The synchronous confirm endpoint (`POST /api/v1/account/billing/confirm-session`)
upgrades the user immediately on the post-checkout redirect even without the
CLI running. The webhook is still required for everything that happens
*after* checkout (renewals, dunning, cancellations).

### Observability (G16)

Distributed traces are emitted via OTLP when `OTEL_ENABLED=true`. SQL bodies
are hashed as `db.statement.hash` by default; set `OTEL_CAPTURE_SQL_TEXT=true`
to record raw statements (privacy-sensitive). Tune `OTEL_SAMPLER_RATIO` in
production (default 1.0 = sample every trace). On shutdown the SDK can take
~30 s to flush pending spans, so orchestrator `terminationGracePeriodSeconds`
should be ≥ `SHUTDOWN_GRACE_PERIOD_SECONDS + 35`.

```env
OTEL_ENABLED=false                          # off by default
OTEL_SERVICE_NAME=mcp-db-agent
OTEL_OTLP_ENDPOINT=http://localhost:4317    # OTel Collector
OTEL_OTLP_PROTOCOL=grpc                     # or "http"
OTEL_OTLP_INSECURE=true
OTEL_SAMPLER_RATIO=1.0
OTEL_CAPTURE_SQL_TEXT=false
```

## Connecting MCP Clients (HTTP mode)

After starting the server (`uvicorn src.app:app`), register a user:

```bash
# Register
curl -X POST http://localhost:8000/api/v1/users/register \
  -H "Content-Type: application/json" \
  -d '{"database_url": "postgresql://user:pass@host/db", "llm_provider": "anthropic", "anthropic_api_key": "sk-ant-..."}'
# → {"user_id": "...", "api_key": "mdbk_...", "warning": "Store this key now."}

# Configure Claude Desktop (claude_desktop_config.json):
{
  "mcpServers": {
    "db-agent": {
      "url": "http://localhost:8000/mcp/",
      "headers": { "X-API-Key": "mdbk_..." }
    }
  }
}
```

## Testing Notes

- `asyncio_mode = "auto"` is set in `pyproject.toml` — async test functions need no `@pytest.mark.asyncio`.
- Integration tests (`test_sql_generator.py`, `test_sql_executor.py`) require a populated `demo.db` and valid API keys in `.env`. Run `scripts/seed_demo_db.py` first.
- The executor tests assume `demo.db` contains exactly 500 users (hardcoded `assert rows[0]["total"] == 500`).
- Executor intentionally does **not** catch exceptions — tests for error propagation (`test_execute_raises_on_*`) verify this contract.
- `SQLExecutor` now requires an injected `ThreadPoolExecutor` — all tests construct one with `ThreadPoolExecutor(max_workers=2)`.

## Demo Database Schema

The demo SQLite database (`demo.db`) has four tables: `users`, `products`, `orders`, `order_items`. Seeded with 500 users, 100 products, 2000 orders, 5000 order_items spanning 2023–2024. Used for all integration tests and Claude Desktop demos.

## Security Model

See `MIGRATION_PLAN.md §3` for the full threat model. Key points:
- User-supplied `database_url` is validated by `src/auth/url_guard.py` (T1, T9) before any connection attempt.
- Database URLs and LLM keys are Fernet-encrypted at rest (T6).
- SQL is validated for dangerous functions and patterns before execution (T2).
- Per-request ContextVar scoping prevents cross-tenant data leaks (T3).
- Per-user rate limits and fallback-LLM quotas limit cost abuse (T4, T5).
