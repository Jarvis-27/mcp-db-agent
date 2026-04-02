# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

An MCP (Model Context Protocol) server that exposes any PostgreSQL or SQLite database as a natural-language queryable endpoint. Any MCP client (Claude Desktop, Cursor, VS Code Copilot) can connect and ask questions in plain English. The server introspects the schema, generates SQL via an LLM, validates it for safety, executes it, and returns structured JSON — with a self-correction retry loop if execution fails.

## Commands

**Package manager: `uv` only** — do not use pip or Poetry.

```bash
# Install all dependencies
uv sync

# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_sql_validator.py

# Run a single test by name
uv run pytest tests/test_sql_executor.py::test_execute_aggregation_count

# Lint and format
uv run ruff check .
uv run ruff format .

# Run the MCP server (stdio transport for Claude Desktop)
uv run src/server.py

# Debug with MCP Inspector (requires Node.js)
npx @modelcontextprotocol/inspector uv run src/server.py

# Seed the demo SQLite database
uv run scripts/seed_demo_db.py
```

## Architecture

The pipeline for a natural-language query flows through these layers:

```
MCP Client
    → FastMCP server (src/server.py)           # tool/resource registration, JSON-RPC
        → ask_database tool (src/tools/)
            → SchemaInspector (src/core/)       # SQLAlchemy introspection → schema string
            → SQLGenerator (src/core/)          # schema + question → LLM → raw SQL
            → SQLValidator (src/core/)          # blocks writes, checks table refs, injects LIMIT
            → SQLExecutor (src/core/)           # runs query in thread pool with timeout
            → SelfCorrector (src/core/)         # retry loop: error → LLM fix → re-validate → re-execute
```

### Key components

- **`src/config.py`** — `Settings` (pydantic-settings) loaded from `.env`. All tunable parameters live here: `DATABASE_URL`, `LLM_PROVIDER`, model names, `MAX_QUERY_ROWS`, `QUERY_TIMEOUT_SECONDS`, `MAX_SELF_CORRECTION_RETRIES`. Import the singleton `settings` object.

- **`src/core/schema_inspector.py`** — `SchemaInspector` wraps SQLAlchemy `inspect()`. Key methods: `get_full_schema()` returns a compact DDL-like string injected into the LLM prompt; `get_table_detail()` includes sample values per column; `get_tables_with_counts()` and `get_sample_rows()` back the `list_tables` and `get_sample_data` MCP tools.

- **`src/core/sql_generator.py`** — `SQLGenerator` selects either `anthropic.AsyncAnthropic` or `groq.AsyncGroq` based on `settings.llm_provider`. The `generate()` method embeds the full schema in the prompt and strips markdown fences from the response via `_clean_sql()`. Default dialect is `"sqlite"`.

- **`src/core/sql_validator.py`** — `SQLValidator.validate()` runs three checks in order: (1) forbid write DML/DDL keywords via `sqlparse`, (2) verify all referenced tables exist via regex extraction + `SchemaInspector.get_table_names()`, (3) auto-inject `LIMIT 100` for plain SELECTs without aggregation. Returns a `ValidationResult` dataclass; `modified_sql` carries the LIMIT-injected version when check 3 triggers.

- **`src/core/sql_executor.py`** — `SQLExecutor.execute()` is async; runs the synchronous SQLAlchemy call in a thread pool via `asyncio.run_in_executor` and enforces `query_timeout_seconds` with `asyncio.wait_for`. PostgreSQL connections use `REPEATABLE READ`; SQLite uses default isolation. Exceptions are **not** caught here — the SelfCorrector handles retries.

- **`src/core/self_corrector.py`** *(planned)* — Orchestrates the retry loop: call `SQLGenerator.generate()`, then `SQLValidator.validate()`, then `SQLExecutor.execute()`. On failure, sends the failed SQL + error + history back to the LLM for correction. Max retries from `settings.max_self_correction_retries`.

- **`src/server.py`** *(planned)* — `FastMCP` instance with 4 tools (`ask_database`, `list_tables`, `describe_schema`, `get_sample_data`) and 1 resource (`schema://overview`).

## Configuration

Copy `.env.example` to `.env` and fill in values:

```
DATABASE_URL=sqlite:///./demo.db        # or postgresql://user:pass@host/db
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...
LLM_PROVIDER=anthropic                  # or "groq" for free-tier development
CLAUDE_MODEL=claude-sonnet-4-6
GROQ_MODEL=llama-3.3-70b-versatile
MAX_QUERY_ROWS=100
QUERY_TIMEOUT_SECONDS=30
MAX_SELF_CORRECTION_RETRIES=3
```

## Testing Notes

- `asyncio_mode = "auto"` is set in `pyproject.toml` — async test functions need no `@pytest.mark.asyncio` decorator.
- Integration tests (`test_sql_generator.py`, `test_sql_executor.py`) require a populated `demo.db` and valid API keys in `.env`. Run `scripts/seed_demo_db.py` first.
- The executor tests assume `demo.db` contains exactly 500 users (hardcoded `assert rows[0]["total"] == 500`).
- Executor intentionally does **not** catch exceptions — tests for error propagation (`test_execute_raises_on_*`) verify this contract.

## Demo Database Schema

The demo SQLite database (`demo.db`) has four tables: `users`, `products`, `orders`, `order_items`. Seeded with 500 users, 100 products, 2000 orders, 5000 order_items spanning 2023–2024. Used for all integration tests and Claude Desktop demos.
