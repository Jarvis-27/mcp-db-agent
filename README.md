# MCP Database Analytics Agent

A Model Context Protocol (MCP) server that turns any PostgreSQL or SQLite database into a natural-language queryable endpoint. Connect it to Claude Desktop, Cursor, VS Code Copilot, or any other MCP-compatible client and ask questions in plain English — the server handles schema introspection, SQL generation, safety validation, execution, and structured result formatting, with an automatic self-correction retry loop when a query fails.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      MCP CLIENTS                            │
│  Claude Desktop  │  Cursor  │  ChatGPT  │  VS Code Copilot  │
└────────┬────────────┬──────────┬────────────┬───────────────┘
         │            │          │            │
         │     MCP Protocol (stdio / Streamable HTTP)
         │            │          │            │
┌────────▼────────────▼──────────▼────────────▼───────────────┐
│                   MCP SERVER LAYER                           │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              FastMCP Server Runtime                  │    │
│  │  • Tool registration & discovery                    │    │
│  │  • JSON-RPC handling                                │    │
│  │  • Transport management (stdio + HTTP)              │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │                                    │
│  ┌──────────────────────▼──────────────────────────────┐    │
│  │              TOOL: ask_database                      │    │
│  │                                                      │    │
│  │  ┌──────────┐  ┌──────────┐  ┌───────────────────┐  │    │
│  │  │ Schema   │  │ Query    │  │ Self-Correction    │  │    │
│  │  │ Inspector│→ │ Generator│→ │ Loop (max 3)       │  │    │
│  │  └──────────┘  └──────────┘  └─────────┬─────────┘  │    │
│  │                                         │            │    │
│  │  ┌──────────────┐  ┌───────────────────▼─────────┐  │    │
│  │  │ Result       │← │ Query Executor              │  │    │
│  │  │ Formatter    │  │ (SQLAlchemy + safety check)  │  │    │
│  │  └──────────────┘  └─────────────────────────────┘  │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │  TOOLS: list_tables · describe_schema · get_sample_data   │
│  │  · query_history                                     │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              RESOURCE: schema://overview              │    │
│  │  Full database schema as context for the LLM client   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
└──────────────────────────┬───────────────────────────────────┘
                           │
                    SQLAlchemy Engine
                           │
              ┌────────────▼────────────┐
              │     DATABASE LAYER       │
              │  PostgreSQL  │  SQLite   │
              └─────────────────────────┘
```

### Request pipeline (`ask_database`)

```
Question
  → SchemaInspector   — introspects live schema into a compact DDL string
  → SQLGenerator      — sends schema + question to the LLM, returns raw SQL
  → SQLValidator      — blocks writes, checks table names, injects LIMIT
  → SQLExecutor       — runs query in a thread pool with a timeout
  → SelfCorrector     — on any failure: sends error + failed SQL back to LLM,
                        retries up to max_self_correction_retries times
  → ResultFormatter   — serialises rows to JSON (handles datetime, Decimal, bytes)
```

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Python | 3.11+ | [python.org](https://python.org) |
| uv | latest | Windows: `irm https://astral.sh/uv/install.ps1 \| iex` · Unix: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 18+ | [nodejs.org](https://nodejs.org) — only needed for MCP Inspector |
| Docker Desktop | latest | [docker.com](https://docker.com) — only needed for the PostgreSQL deployment path |

**API keys** (at least one required):

- **Anthropic** — [console.anthropic.com](https://console.anthropic.com) — used as the primary SQL generation LLM
- **Groq** — [console.groq.com](https://console.groq.com) — free-tier fallback (Llama 3.3 70B)

---

## Quick Start

```bash
# 1. Clone and enter the project
git clone <repo-url>
cd mcp-db-agent

# 2. Install all dependencies
uv sync

# 3. Configure environment
cp .env.example .env
# Edit .env — set DATABASE_URL, ANTHROPIC_API_KEY (or GROQ_API_KEY), LLM_PROVIDER

# 4. Seed the demo SQLite database (500 users, 100 products, 2 000 orders)
uv run scripts/seed_demo_db.py

# 5. (Optional) Verify the server starts correctly
uv run src/server.py

# 6. Connect Claude Desktop — add the block below to claude_desktop_config.json
#    (macOS: ~/Library/Application Support/Claude/claude_desktop_config.json)
#    (Windows: %APPDATA%\Claude\claude_desktop_config.json)
```

**Claude Desktop config block:**

```json
{
  "mcpServers": {
    "database-analytics": {
      "command": "uv",
      "args": ["run", "/absolute/path/to/mcp-db-agent/src/server.py"],
      "env": {
        "DATABASE_URL": "sqlite:////absolute/path/to/mcp-db-agent/demo.db",
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "LLM_PROVIDER": "anthropic",
        "CLAUDE_MODEL": "claude-sonnet-4-6",
        "GROQ_API_KEY": "",
        "GROQ_MODEL": "llama-3.3-70b-versatile",
        "MAX_QUERY_ROWS": "100",
        "QUERY_TIMEOUT_SECONDS": "30",
        "MAX_SELF_CORRECTION_RETRIES": "3"
      }
    }
  }
}
```

Restart Claude Desktop and ask: *"How many orders were placed in 2024?"*

---

## Configuration

All settings are loaded from `.env` via `pydantic-settings`. Copy `.env.example` to `.env` and fill in the values — `.env` is gitignored and never committed.

| Variable | Required | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | Yes | — | SQLAlchemy connection string. `sqlite:///./demo.db` or `postgresql://user:pass@host/db` |
| `ANTHROPIC_API_KEY` | If `LLM_PROVIDER=anthropic` | — | Anthropic API key from console.anthropic.com |
| `GROQ_API_KEY` | If `LLM_PROVIDER=groq` | — | Groq API key from console.groq.com |
| `LLM_PROVIDER` | Yes | — | `anthropic` or `groq` |
| `CLAUDE_MODEL` | No | `claude-sonnet-4-6` | Anthropic model ID to use for SQL generation |
| `GROQ_MODEL` | No | `llama-3.3-70b-versatile` | Groq model ID for the free-tier path |
| `MAX_QUERY_ROWS` | No | `100` | Row cap auto-injected as `LIMIT` on unbounded SELECTs |
| `QUERY_TIMEOUT_SECONDS` | No | `30` | Hard timeout for each SQL execution |
| `MAX_SELF_CORRECTION_RETRIES` | No | `3` | Maximum LLM correction cycles before returning an error |
| `TRANSPORT` | No | `stdio` | `stdio` for Claude Desktop / Cursor; `streamable-http` for Docker HTTP mode |

---

## Available Tools

| Tool | Description | Parameters |
|---|---|---|
| `ask_database` | Translate a plain-English question to SQL, execute it, and return structured JSON results. Retries automatically on failure. | `question: str` |
| `list_tables` | List every table in the database with its current row count. Call this first to discover what data is available. | — |
| `describe_schema` | Return column names, types, nullability, primary keys, foreign keys, and sample values for a specific table. | `table_name: str` |
| `get_sample_data` | Return up to 20 raw rows from a table for data exploration. | `table_name: str`, `limit: int` (default 5, capped at 20) |
| `query_history` | Show recent questions, the SQL generated for each, whether they succeeded, and timing. | `limit: int` (default 10) |

### Resource

| URI | Description |
|---|---|
| `schema://overview` | The full database schema in compact DDL-like notation — fetch this to inject the complete schema into your context in one call instead of calling `describe_schema` on every table. |

### `ask_database` response shape

**Success:**
```json
{
  "query": "SELECT ...",
  "row_count": 42,
  "columns": ["col_a", "col_b"],
  "data": [{ "col_a": 1, "col_b": "x" }],
  "attempts": 1
}
```

**Failure (after all retries exhausted):**
```json
{
  "error": "final error message",
  "attempted_sql": "SELECT ...",
  "errors": ["error on attempt 1", "error on attempt 2"],
  "suggestion": "Try rephrasing your question or call the describe_schema tool first."
}
```

---

## Self-Correction Loop

This is the core reliability feature. When SQL generation or execution fails, the server doesn't give up — it sends the error back to the LLM with full context and asks it to fix the query.

```
attempt 1
  └─ generate SQL from question + schema
  └─ validate (safety + table existence + LIMIT injection)
       ├─ validation fails → send (question, bad SQL, error) to LLM → get fixed SQL → attempt 2
       └─ validation passes
            └─ execute
                 ├─ execution fails → send (question, bad SQL, error) to LLM → get fixed SQL → attempt 2
                 └─ execution succeeds → format → return

attempt 2, 3 ... (up to MAX_SELF_CORRECTION_RETRIES)
  └─ same validate → execute path with the LLM-corrected SQL

all retries exhausted → return error JSON with full error history
```

**Each correction prompt includes:**
- The original natural-language question
- The full live database schema (so the LLM can see the correct table and column names)
- The failed SQL
- The exact error message
- All prior errors from the current session

This multi-signal context gives the LLM enough information to fix name typos, wrong join conditions, missing columns, and dialect-specific syntax errors — the most common failure modes in text-to-SQL.

---

## Adding Your Own Database

Change one line in `.env`:

```bash
# SQLite (file path)
DATABASE_URL=sqlite:///./my_database.db

# PostgreSQL (local or cloud)
DATABASE_URL=postgresql://user:password@localhost:5432/my_database

# Neon (serverless PostgreSQL)
DATABASE_URL=postgresql://user:password@ep-xxxx.us-east-2.aws.neon.tech/my_database
```

No code changes required. The `SchemaInspector` reads the live schema at startup and re-introspects on every `ask_database` call, so it works with any schema automatically.

---

## Running Tests

```bash
# Unit tests only (no API keys or demo.db required — fully mocked)
uv run pytest tests/ -m "not integration" -v

# Integration tests (requires demo.db and real API keys in .env)
uv run scripts/seed_demo_db.py   # seed demo.db first
uv run pytest tests/ -m integration -v

# Lint and format check
uv run ruff check .
uv run ruff format --check .

# Debug the server interactively with MCP Inspector (requires Node.js)
npx @modelcontextprotocol/inspector uv run src/server.py
```

The unit test suite (117 tests) covers every layer — schema inspection, SQL validation, SQL generation (mocked LLM), execution (real in-memory SQLite), self-correction retry logic, result formatting, and all four MCP tools — with zero external dependencies.

---

## Deployment

### Local SQLite (stdio transport — Claude Desktop / Cursor)

```bash
uv run src/server.py
```

The server speaks stdio JSON-RPC — configure your MCP client to launch this command directly (see [Quick Start](#quick-start)).

### PostgreSQL + HTTP transport (Docker Compose)

```bash
# Start PostgreSQL and the MCP server as HTTP endpoints
docker compose up --build

# The MCP server is now available at http://localhost:8000
# Connect via HTTP transport in your MCP client config:
#   "url": "http://localhost:8000/mcp"
```

The `docker-compose.yml` starts a `postgres:16` container alongside the MCP server. The server waits for the database health check before accepting connections. Set your LLM API key in `.env` before running.

### Environment variables for Docker

```bash
# Override transport at runtime (default in Dockerfile is streamable-http)
docker run -e TRANSPORT=streamable-http -e DATABASE_URL=... -e ANTHROPIC_API_KEY=... mcp-db-agent
```
