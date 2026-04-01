# MCP Database Analytics Agent — Step-by-Step Build Guide

**Project:** Natural-language database query agent using the MCP protocol  
**End Goal:** An MCP server that any AI client (Claude Desktop, Cursor, Windsurf, VS Code Copilot) can connect to and query any PostgreSQL or SQLite database using plain English.

---

## Prerequisites — Install Before You Begin

Before writing a single line of code, ensure the following are installed on your machine:

1. **Python 3.11 or higher** — Required for the MCP SDK and all async features. Download from python.org. Verify with `python --version`.

2. **uv** — The package manager used by the MCP ecosystem. Do not use pip or Poetry for this project.
   - Windows: Run `irm https://astral.sh/uv/install.ps1 | iex` in PowerShell
   - macOS/Linux: Run `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - After install, verify with `uv --version`

3. **Node.js 18+** — Required only for the MCP Inspector debugging tool (which runs via `npx`). Download from nodejs.org.

4. **Docker Desktop** — Required in Week 2 when you switch from SQLite to a real PostgreSQL instance. Install from docker.com. You can skip this initially and come back to it on Day 7.

5. **Claude Desktop** — The primary client you'll test against. Download from claude.ai. You'll need an Anthropic account.

6. **API Keys** — Obtain before Day 2:
   - **Anthropic API key**: From console.anthropic.com — used as the primary SQL generation LLM
   - **Groq API key**: From console.groq.com — free tier, used as the fallback LLM during development to save costs

---

## Phase 1: Project Scaffold

### Step 1 — Initialize the uv Project

Navigate to the directory where you want to create the project, then initialize a new uv-managed Python project. The project name should be `mcp-db-agent`.

- Use `uv init mcp-db-agent` to scaffold the project. This creates a `pyproject.toml`, a basic `main.py`, and a `.python-version` file.
- Delete the auto-generated `main.py` — you won't need it. Your entrypoint will be `src/server.py`.
- Change into the project directory: `cd mcp-db-agent`

### Step 2 — Set Up the Directory Structure

Manually create the following folder structure inside the project root. Use your file explorer or `mkdir` commands:

```
mcp-db-agent/
├── src/
│   ├── tools/
│   ├── core/
│   └── resources/
├── tests/
└── scripts/
```

Create empty `__init__.py` files in every folder under `src/` (i.e., `src/__init__.py`, `src/tools/__init__.py`, `src/core/__init__.py`, `src/resources/__init__.py`). These mark directories as Python packages.

### Step 3 — Install All Dependencies

Run these `uv add` commands from the project root. Each command adds the package to `pyproject.toml` and installs it into the virtual environment that uv manages automatically:

**Core runtime dependencies:**
- `uv add mcp` — The official Anthropic MCP Python SDK. This includes FastMCP, the high-level server framework you'll use.
- `uv add sqlalchemy` — Database abstraction layer. Handles both PostgreSQL and SQLite with the same API.
- `uv add sqlparse` — SQL parsing library for the safety validator.
- `uv add anthropic` — Anthropic Python SDK for Claude API calls (SQL generation LLM).
- `uv add groq` — Groq Python SDK for Llama 3.3 as a free-tier fallback LLM.
- `uv add pydantic-settings` — Type-safe configuration management from `.env` files.
- `uv add psycopg2-binary` — PostgreSQL database adapter required by SQLAlchemy for Postgres connections. The `binary` variant avoids needing to compile from source.

**Development dependencies** (add with `--dev` flag so they don't ship in production):
- `uv add --dev pytest` — Test runner.
- `uv add --dev pytest-asyncio` — Enables testing of async functions with pytest.
- `uv add --dev ruff` — Fast Python linter and formatter (replaces black + flake8).

After running all installs, verify your `pyproject.toml` has a `[project]` section with a `dependencies` list containing all core packages, and a `[dependency-groups]` or `[tool.uv.dev-dependencies]` section with the dev tools.

### Step 4 — Configure pyproject.toml

Open `pyproject.toml` and ensure the following settings are present beyond what uv auto-generated:

- Set `requires-python = ">=3.11"` in the `[project]` section.
- Add a `[tool.pytest.ini_options]` section and set `asyncio_mode = "auto"` — this tells pytest-asyncio to treat all async test functions as async tests without needing individual `@pytest.mark.asyncio` decorators.
- Add a `[tool.ruff]` section and set `line-length = 100` and `target-version = "py311"`.

### Step 5 — Create the `.env` File

Create a `.env` file in the project root (next to `pyproject.toml`). This file will never be committed to git. Add the following variables:

- `DATABASE_URL` — Start with an SQLite path, e.g., `sqlite:///./demo.db`. You'll switch this to a PostgreSQL URL in Week 2.
- `ANTHROPIC_API_KEY` — Your Anthropic API key from Step 0.
- `GROQ_API_KEY` — Your Groq API key.
- `LLM_PROVIDER` — Set to `anthropic` initially. Can be switched to `groq` at runtime.
- `CLAUDE_MODEL` — Set to `claude-sonnet-4-6` (the latest capable model as of April 2026).
- `GROQ_MODEL` — Set to `llama-3.3-70b-versatile` (the most capable free Groq model).
- `MAX_QUERY_ROWS` — Set to `100`. This is the default row limit injected into queries.
- `QUERY_TIMEOUT_SECONDS` — Set to `30`.
- `MAX_SELF_CORRECTION_RETRIES` — Set to `3`.

Also create a `.env.example` file with the same keys but empty/placeholder values — this is safe to commit to git and shows collaborators what variables are needed.

Create a `.gitignore` file (if not already present) and add `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `demo.db` to it.

---

## Phase 2: Configuration Module

### Step 6 — Build `src/config.py`

This module reads all `.env` values into a typed Python object using `pydantic-settings`.

**Library:** `pydantic-settings` — import `BaseSettings` from it.

**What to implement:** A single `Settings` class that inherits from `BaseSettings`. Each environment variable from Step 5 becomes a typed field on this class (string fields for URLs and keys, integer fields for numeric limits). Configure the class to auto-read from the `.env` file using the `model_config` attribute with `env_file=".env"`.

Instantiate a single `settings` object at module level. All other modules import from this single instance. This is the only place in the codebase where environment variables are read.

---

## Phase 3: Database Foundation

### Step 7 — Seed the Demo Database (`scripts/seed_demo_db.py`)

Before building the query pipeline, you need data to query. This script creates a realistic e-commerce SQLite database.

**Libraries:** `sqlalchemy` for DDL and data insertion, Python's built-in `random` and `datetime` modules for generating fake data.

**What to implement:** A script that, when run via `uv run python scripts/seed_demo_db.py`, creates a `demo.db` SQLite file with four tables:

- **`users`**: columns for id (primary key), name, email (unique), country, and created_at timestamp. Seed with 500 rows spread across countries like US, UK, India, Germany, Canada.
- **`products`**: columns for id, name, category (values like "Electronics", "Clothing", "Books", "Home", "Sports"), price (decimal), stock_quantity, and created_at. Seed with 100 rows.
- **`orders`**: columns for id, user_id (foreign key to users), status (values: "pending", "shipped", "delivered", "cancelled"), total_amount, and created_at. Seed with 2,000 rows spread across dates from 2023-01-01 to 2024-12-31.
- **`order_items`**: columns for id, order_id (FK to orders), product_id (FK to products), quantity, and unit_price. Seed with 5,000 rows.

Use SQLAlchemy's `Table`, `Column`, `MetaData`, and `insert()` constructs. After seeding, print a summary: table names and row counts.

Run the script once with `uv run python scripts/seed_demo_db.py` to generate `demo.db`. Verify it was created.

### Step 8 — Build `src/core/schema_inspector.py`

This is the most important module in the entire project. The quality of SQL generation depends entirely on the quality of the schema context fed to the LLM.

**Library:** `sqlalchemy` — use `sqlalchemy.inspect()` to get an `Inspector` object from your engine.

**What to implement — `SchemaInspector` class with these methods:**

- **`__init__(engine)`**: Accepts a SQLAlchemy `Engine` object. Stores it and creates an `Inspector` via `sqlalchemy.inspect(engine)`.

- **`get_table_names()`**: Returns a list of all table names in the database using `inspector.get_table_names()`.

- **`get_columns(table_name)`**: Returns column metadata for a table using `inspector.get_columns(table_name)`. Each column entry includes name, type, nullable, and default.

- **`get_primary_keys(table_name)`**: Returns the primary key constraint using `inspector.get_pk_constraint(table_name)`.

- **`get_foreign_keys(table_name)`**: Returns foreign key relationships using `inspector.get_foreign_keys(table_name)`. Each FK entry includes the local column(s), referred table, and referred column(s).

- **`get_sample_values(table_name, column_name, limit=5)`**: Executes a `SELECT DISTINCT column LIMIT limit` query against the live database and returns the results as a list. This is critical — it shows the LLM actual enum values (like "pending", "shipped") instead of making it guess.

- **`get_full_schema()`**: Calls all the above methods for every table and assembles a single string in compact DDL-like notation. Format: each table starts with `TABLE: tablename`, followed by column definitions (`columnname TYPE [PRIMARY KEY]`), then foreign key relationships. Tables separated by blank lines. This string is the schema context passed to the LLM.

- **`get_table_detail(table_name)`**: Returns full detail for a single table — columns with types, PKs, FKs, and sample values for each column (using `get_sample_values`). Returns as a formatted string.

- **`get_tables_with_counts()`**: Returns a list of dicts, each with `table_name` and `row_count`. Execute a `SELECT COUNT(*) FROM tablename` for each table.

- **`get_sample_rows(table_name, limit=5)`**: Returns the first N rows from a table as a list of dicts (column name → value).

---

## Phase 4: SQL Generation Pipeline

### Step 9 — Build `src/core/sql_generator.py`

This module translates natural language questions into SQL using an LLM.

**Libraries:**
- `anthropic` — for calling Claude (primary LLM). Use `anthropic.AsyncAnthropic()` for async calls. The method is `client.messages.create()` with `model`, `max_tokens`, and `messages` parameters.
- `groq` — for Groq fallback. The Groq SDK mirrors the OpenAI SDK interface. Use `groq.AsyncGroq()` and the same `client.chat.completions.create()` method as OpenAI.

**What to implement — `SQLGenerator` class:**

- **`__init__(settings, schema_inspector)`**: Reads `LLM_PROVIDER` from settings. Instantiates either `AsyncAnthropic` (with the Anthropic API key) or `AsyncGroq` (with the Groq API key) based on the provider setting. Stores the `SchemaInspector` reference.

- **`_build_prompt(question, dialect)`**: Assembles the full prompt string. Call `schema_inspector.get_full_schema()` to get the schema. Build a prompt that includes:
  - A role statement ("You are a SQL expert")
  - The full database schema
  - The target SQL dialect (postgresql or sqlite)
  - Six explicit rules: use only existing tables/columns, always alias tables, add LIMIT unless aggregating, use proper date functions for the dialect, use LEFT JOIN for potentially-missing relationships, return ONLY raw SQL with no markdown or explanation
  - The user's question

- **`async generate(question, dialect="sqlite")`**: Calls `_build_prompt`, sends it to the configured LLM client, and returns the raw SQL string. Strip any leading/trailing whitespace, backticks, or markdown code fences from the response before returning.

- For Anthropic calls: Use `model=settings.claude_model`, `max_tokens=1024`, send the prompt as a user message.
- For Groq calls: Use `model=settings.groq_model`, `max_tokens=1024`, use the chat completions format with a system message ("You are a SQL expert. Return only SQL.") and a user message containing the prompt.

### Step 10 — Build `src/core/sql_validator.py`

This is the security layer. Every generated SQL query passes through this before execution.

**Library:** `sqlparse` — import it, use `sqlparse.parse(sql)` to get a list of parsed statements, then iterate tokens to inspect types and values.

**What to implement — `SQLValidator` class:**

Define a `ValidationResult` dataclass with fields: `is_valid` (bool), `error` (str, optional), `warning` (str, optional), `modified_sql` (str, optional).

- **`__init__(schema_inspector)`**: Stores a reference to the `SchemaInspector`.

- **`validate(sql)`**: Runs three checks in sequence and returns a `ValidationResult`:

  1. **Write operation check**: Parse the SQL with sqlparse. Iterate all tokens. If any token's type is `sqlparse.tokens.Keyword.DML` (Data Manipulation Language) and its value (uppercased) is in a forbidden set — INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, GRANT, REVOKE, EXEC, EXECUTE — return `ValidationResult(is_valid=False, error="Write operations are not allowed")`.

  2. **Table existence check**: Use regex or sqlparse to extract table names referenced in the FROM and JOIN clauses. Call `schema_inspector.get_table_names()` to get the actual list. If any referenced table doesn't exist, return `ValidationResult(is_valid=False, error="Table 'X' does not exist in the database")`.

  3. **LIMIT check**: If the SQL (uppercased) doesn't contain `LIMIT` and also doesn't contain `GROUP BY`, `COUNT(`, `SUM(`, `AVG(`, `MAX(`, or `MIN(` — the query is likely a full table scan. Return `ValidationResult(is_valid=True, warning="No LIMIT added", modified_sql=sql.rstrip(";") + " LIMIT 100;")`. Use `modified_sql` to auto-inject the limit.

  If all checks pass, return `ValidationResult(is_valid=True)`.

### Step 11 — Build `src/core/sql_executor.py`

This module runs validated SQL against the database.

**Library:** `sqlalchemy` — use `engine.connect()` to get a connection. Use `sqlalchemy.text()` to wrap raw SQL strings into executable objects (required in SQLAlchemy 2.0).

**What to implement — `SQLExecutor` class:**

- **`__init__(engine, settings)`**: Stores the engine and reads `QUERY_TIMEOUT_SECONDS` from settings.

- **`async execute(sql)`**: This is intentionally synchronous at the SQLAlchemy level (SQLAlchemy's core is synchronous) but wrapped to be called from async code. Open a connection with `engine.connect()` using a context manager. Set execution options to enforce a timeout and read-only isolation. Execute the SQL using `conn.execute(sqlalchemy.text(sql))`. Fetch all results with `.mappings().all()` to get a list of dict-like objects. Convert to plain dicts and return.

- If execution raises any exception, do not catch it here — let it bubble up to the `SelfCorrector`. The executor's job is only to run the query cleanly.

- For PostgreSQL: you can set `isolation_level="REPEATABLE READ"` to prevent dirty reads. For SQLite: `isolation_level=None` (autocommit) works fine for read-only queries.

### Step 12 — Build `src/core/self_corrector.py`

This is the differentiating feature — intelligent retry on failure.

**Libraries:** None beyond the modules already built. This class composes `SQLGenerator`, `SQLValidator`, and `SQLExecutor`.

**What to implement — `SelfCorrector` class:**

- **`__init__(generator, validator, executor, settings)`**: Stores references to all three pipeline components. Reads `MAX_SELF_CORRECTION_RETRIES` from settings.

- **`async execute_with_correction(question, dialect="sqlite")`**: Main entry point. Returns a result dict with keys: `success`, `sql`, `data`, `attempts`, `error`, `errors`.

  **Algorithm:**
  1. Call `generator.generate(question, dialect)` to get the initial SQL.
  2. Maintain a list `errors_so_far = []` and a loop counter `attempt = 0`.
  3. Loop up to `MAX_SELF_CORRECTION_RETRIES` times:
     a. Call `validator.validate(sql)`. If `is_valid` is False, append the error to `errors_so_far` and call `_fix_sql(question, sql, error, errors_so_far)` to get a corrected SQL. Continue the loop.
     b. If validation passed but there's a `modified_sql` (auto-injected LIMIT), use `modified_sql` going forward.
     c. Try to call `executor.execute(sql)` inside a try/except. On success, return the result dict with `success=True`.
     d. On exception, append the error message to `errors_so_far`. Call `_fix_sql` with the exception message to get a corrected SQL. Increment the attempt counter. Continue the loop.
  4. If all retries are exhausted, return a result dict with `success=False`, `errors=errors_so_far`, and `last_sql` set to the last attempted SQL.

- **`async _fix_sql(question, failed_sql, error, error_history)`**: Builds a correction prompt that includes the original question, the failed SQL, the error message, and the history of previous errors. Calls `generator.llm.generate(correction_prompt)` (you may need to expose a raw generate method on the generator for this). Returns the corrected SQL.

### Step 13 — Build `src/core/result_formatter.py`

This module transforms raw database rows into a clean, structured response.

**Libraries:** Python's built-in `json` module. No external dependencies.

**What to implement — `ResultFormatter` class:**

- **`format(sql, rows, attempts)`**: Takes the executed SQL, the list of row dicts, and the number of attempts used. Returns a dict with:
  - `query`: the SQL that was executed
  - `row_count`: number of rows returned
  - `columns`: list of column names (from `rows[0].keys()` if rows is non-empty, else empty list)
  - `data`: list of row dicts, capped at 100 rows
  - `attempts`: how many retries were needed

- **`format_error(error, last_sql, errors)`**: For failure cases. Returns a dict with `error`, `attempted_sql`, `errors` (the full retry history), and a `suggestion` message like "Try rephrasing your question or call the `describe_schema` tool first."

- Implement a custom JSON serializer for types that aren't JSON-serializable by default: `datetime.datetime`, `datetime.date`, `decimal.Decimal`. Pass this as the `default` parameter to `json.dumps()`.

---

## Phase 5: MCP Tools

### Step 14 — Build `src/tools/list_tables.py`

This tool wraps `schema_inspector.get_tables_with_counts()`.

**What to implement:** A function `list_tables(inspector)` that calls `inspector.get_tables_with_counts()` and returns the result serialized to a JSON string with `json.dumps(..., indent=2)`.

### Step 15 — Build `src/tools/describe_schema.py`

This tool exposes detailed schema information for a specific table.

**What to implement:** A function `describe_schema(table_name, inspector)` that calls `inspector.get_table_detail(table_name)`. If `table_name` is not in `inspector.get_table_names()`, return a JSON error message: `{"error": "Table 'X' not found. Call list_tables to see available tables."}`.

### Step 16 — Build `src/tools/get_sample_data.py`

This tool returns raw rows for data exploration.

**What to implement:** A function `get_sample_data(table_name, limit, inspector)` where `limit` defaults to 5 and is capped at 20. Call `inspector.get_sample_rows(table_name, limit)` and return as JSON.

### Step 17 — Build `src/tools/ask_database.py`

The core tool. Composes the entire pipeline.

**What to implement:** An async function `ask_database(question, corrector, formatter, dialect)` that:
1. Calls `await corrector.execute_with_correction(question, dialect)`
2. If `result["success"]` is True, calls `formatter.format(...)` and returns the JSON string
3. If False, calls `formatter.format_error(...)` and returns the JSON string

---

## Phase 6: MCP Resources

### Step 18 — Build `src/resources/schema_overview.py`

MCP Resources are like read-only endpoints that the LLM client can fetch to inject into its context.

**What to implement:** A function `get_schema_overview(inspector)` that calls `inspector.get_full_schema()` and returns the schema string. This function will be registered with a URI of `schema://overview` in the server.

---

## Phase 7: MCP Server

### Step 19 — Build `src/server.py`

This is the entrypoint that wires everything together and registers all tools and resources with the MCP runtime.

**Library:** `mcp` — specifically `from mcp.server.fastmcp import FastMCP`. FastMCP is the high-level decorator-based API in the official MCP Python SDK.

**What to implement:**

1. **Initialize settings**: Import `Settings` from `src/config.py`. Create a `settings` instance.

2. **Create the database engine**: Use `sqlalchemy.create_engine(settings.database_url)` to create an engine. This is shared across all requests.

3. **Initialize all pipeline components**: Instantiate `SchemaInspector(engine)`, `SQLGenerator(settings, inspector)`, `SQLValidator(inspector)`, `SQLExecutor(engine, settings)`, `SelfCorrector(generator, validator, executor, settings)`, and `ResultFormatter()`.

4. **Determine SQL dialect**: Check if the database URL starts with `sqlite` or `postgresql` and set a `dialect` variable accordingly. Pass this to tools that need it.

5. **Create the FastMCP server instance**: `mcp = FastMCP("Database Analytics Agent")`. The string is the server name shown to clients.

6. **Register the schema resource** using the `@mcp.resource("schema://overview")` decorator on a function that calls `get_schema_overview(inspector)` and returns the schema string. The function's docstring becomes the resource description visible to clients.

7. **Register the `list_tables` tool** using the `@mcp.tool()` decorator on a function that calls `list_tables(inspector)`. The function's docstring becomes the tool description — write it clearly: "List all tables in the database with their row counts."

8. **Register the `describe_schema` tool** with a `table_name: str` parameter. Docstring should explain it returns columns, types, primary keys, foreign keys, and sample values. Parameter docstring should say "Name of the table to describe."

9. **Register the `get_sample_data` tool** with `table_name: str` and `limit: int = 5` parameters. Docstring: "Get sample rows from a table to understand the data format and values."

10. **Register the `ask_database` tool** as an async function with a `question: str` parameter. This is the core tool. Write a detailed docstring: "Ask a natural language question about the database. The agent generates SQL, validates it for safety, executes it, and returns structured results. Automatically retries and self-corrects on errors."

11. **Add the `if __name__ == "__main__":` block**: Call `mcp.run(transport="stdio")` for local Claude Desktop use.

---

## Phase 8: First Test — MCP Inspector

### Step 20 — Test with MCP Inspector

Before connecting Claude Desktop, validate the server works correctly using the MCP Inspector — a developer tool that sends JSON-RPC messages directly to your server.

**Tool:** MCP Inspector — runs via Node.js/npm. No separate install needed.

**Run the inspector against your server:**
```
npx @modelcontextprotocol/inspector uv --directory /path/to/mcp-db-agent run src/server.py
```

This launches a web UI in your browser. Use it to:

1. **Resources tab**: Click on `schema://overview`. Verify it returns your schema with all four tables (users, products, orders, order_items) and their columns. If this is empty or errors, debug `schema_inspector.py`.

2. **Tools tab → list_tables**: Click the tool and invoke it with no arguments. Verify it returns all four tables with correct row counts (500 users, 100 products, 2000 orders, 5000 order_items). If counts are 0, re-run the seed script.

3. **Tools tab → describe_schema**: Invoke with `table_name = "orders"`. Verify you see all columns with types, the foreign key to users, and sample values for the `status` column showing "pending", "shipped", etc.

4. **Tools tab → get_sample_data**: Invoke with `table_name = "order_items"`, `limit = 3`. Verify three rows are returned with all columns populated.

5. **Tools tab → ask_database**: Invoke with `question = "How many orders are in each status?"`. This is the full pipeline test. Verify:
   - The response is valid JSON
   - The `query` field contains a syntactically correct SQL GROUP BY query
   - The `data` field contains rows with status names and counts
   - The `attempts` field shows 1 (no corrections needed for this simple query)

Fix any issues before proceeding to Claude Desktop integration.

---

## Phase 9: Claude Desktop Integration

### Step 21 — Configure Claude Desktop

Claude Desktop reads its MCP server configuration from a JSON config file.

**Config file location:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**What to configure:** Open the config file (create it if it doesn't exist) and add your server under the `mcpServers` key. The server entry needs:
- `command`: `"uv"`
- `args`: `["--directory", "/absolute/path/to/mcp-db-agent", "run", "src/server.py"]`
- `env`: an object with `DATABASE_URL` (pointing to your `demo.db` absolute path), `ANTHROPIC_API_KEY`, and `GROQ_API_KEY`

Also create a `claude_desktop_config.json` file in your project root as a reference template (replace actual API keys with placeholders before committing).

**After saving:** Fully quit and restart Claude Desktop. Open a new conversation. You should see a hammer icon (tools) indicating MCP tools are available. Click it to verify your four tools and one resource are listed.

### Step 22 — End-to-End Testing with Claude Desktop

Test at least these 10 questions to validate all parts of the pipeline:

1. "What tables are available in this database?" — Tests `list_tables`
2. "Describe the orders table" — Tests `describe_schema`
3. "Show me 3 sample rows from the products table" — Tests `get_sample_data`
4. "How many orders are there in each status?" — Tests basic GROUP BY
5. "What are the top 5 products by total revenue?" — Tests JOIN + aggregation
6. "Show me monthly revenue trends for 2024" — Tests date functions
7. "Which countries have the most customers?" — Tests simple aggregation
8. "Who are customers with more than 3 orders?" — Tests HAVING clause
9. "What's the average order value by product category?" — Tests multi-table JOIN
10. "How many orders were placed each month in 2023?" — Tests date grouping

For each question, check:
- The response includes the SQL that was used
- The data looks correct
- No errors or crashes

Fix any edge cases you discover: NULL handling, empty results, very long column names, etc.

---

## Phase 10: PostgreSQL Support

### Step 23 — Spin Up a PostgreSQL Instance

**Option A (local Docker — recommended for development):**
Run this Docker command to start a PostgreSQL 16 container:
```
docker run --name postgres-dev -e POSTGRES_USER=admin -e POSTGRES_PASSWORD=secret -e POSTGRES_DB=ecommerce -p 5432:5432 -d postgres:16
```

Verify it's running: `docker ps`. Connect to it: `docker exec -it postgres-dev psql -U admin -d ecommerce`.

**Option B (cloud — no Docker needed):**
Create a free database on Neon.tech (neon.tech). They provide a ready-to-use PostgreSQL connection string. No local setup needed.

### Step 24 — Seed PostgreSQL with Demo Data

Modify `scripts/seed_demo_db.py` to accept a `--db-url` command-line argument (use Python's built-in `argparse` module). When the PostgreSQL URL is passed, the same seeding logic creates the tables and data in PostgreSQL.

Run: `uv run python scripts/seed_demo_db.py --db-url "postgresql://admin:secret@localhost:5432/ecommerce"`

Verify the data exists by connecting to the database and running `SELECT COUNT(*) FROM users;`.

### Step 25 — Handle PostgreSQL-Specific Types

SQLAlchemy's `inspect()` returns SQLAlchemy type objects. When serializing schema info to strings for the LLM, handle PostgreSQL-specific types:

- `TIMESTAMPTZ` — serialize as "TIMESTAMPTZ (timezone-aware datetime)"
- `JSONB` — serialize as "JSONB (JSON data)"
- `UUID` — serialize as "UUID"
- `ARRAY` — serialize as "ARRAY[elementtype]"
- `NUMERIC` / `DECIMAL` — serialize as "DECIMAL(precision, scale)"

In `schema_inspector.py`'s `get_full_schema()`, convert type objects to strings using `str(col['type'])`. Test this against the PostgreSQL database to ensure the schema string is clean and readable.

### Step 26 — Test Dialect Switching

Update the `sql_generator.py` prompt to reference the correct dialect. The `server.py` detects the dialect from the `DATABASE_URL`:

- If URL starts with `postgresql` → dialect is `postgresql`, use `DATE_TRUNC`, `EXTRACT`, `::date` casting
- If URL starts with `sqlite` → dialect is `sqlite`, use `strftime`, `date()`, `julianday()`

Test at least 3 date-related questions against both databases to confirm dialect-correct SQL is generated.

---

## Phase 11: Enhanced Schema Context

### Step 27 — Add Sample Values to Schema

Update `schema_inspector.py`'s `get_full_schema()` to include sample values for columns that appear to be categorical (string columns with fewer than 20 distinct values). For each such column, call `get_sample_values(table, column, limit=5)` and append the values to the column definition in the schema string.

Format: `status VARCHAR (sample values: 'pending', 'shipped', 'delivered', 'cancelled')`

Run the full test suite of 10 questions again after this change. You should observe fewer self-corrections and more accurate filtering conditions.

---

## Phase 12: HTTP Transport (Remote Deployment)

### Step 28 — Add Streamable HTTP Transport

The stdio transport only works when the MCP client runs on the same machine. For team or cloud deployments, you need the HTTP transport.

**Library:** FastMCP supports streamable HTTP natively — no extra libraries needed.

In `server.py`, update the `if __name__ == "__main__":` block to read a `TRANSPORT` environment variable from settings:
- If `TRANSPORT=stdio` → run `mcp.run(transport="stdio")` (default for Claude Desktop)
- If `TRANSPORT=streamable-http` → run `mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)`

Add `TRANSPORT` to `.env` and `.env.example`.

### Step 29 — Dockerize the Server

Create a `Dockerfile` in the project root. The Dockerfile should:

1. Start from `python:3.11-slim` base image
2. Install `uv` using its installation script
3. Copy `pyproject.toml` and the lock file first (for Docker layer caching)
4. Run `uv sync --no-dev` to install only production dependencies
5. Copy the `src/` directory
6. Expose port 8000
7. Set the default command to `uv run src/server.py`
8. Set environment variable `TRANSPORT=streamable-http` in the Dockerfile

Create a `docker-compose.yml` that runs both the MCP server container and a PostgreSQL container together, with the database URL wired as an environment variable from a `.env` file.

Test the Docker build: `docker build -t mcp-db-agent .` then `docker run -p 8000:8000 --env-file .env mcp-db-agent`.

---

## Phase 13: Query History and Caching

### Step 30 — Add Query History Logging

Create a new file `src/core/query_log.py`. Use SQLite (via SQLAlchemy) to maintain a separate log database (a second SQLite file, e.g., `query_log.db`).

**Library:** `sqlalchemy` — create a second engine pointing to `query_log.db`.

**What to implement:** A `QueryLog` class with:
- A `log_query(question, sql, success, row_count, attempts, duration_ms, error)` method that inserts a record into a `query_history` table with all these fields plus a timestamp.
- A `get_recent_queries(limit=10)` method that returns the last N queries.

Integrate this into `server.py`: wrap the `ask_database` tool handler with timing (using `time.monotonic()`) and log every query after execution.

Register a fifth tool: `query_history` — calls `query_log.get_recent_queries()` and returns as JSON. Docstring: "See recent questions asked to the database, the SQL generated, and whether they succeeded."

### Step 31 — Add LRU Query Cache

Add a simple in-memory cache to `server.py` using Python's built-in `functools.lru_cache` or a plain `dict` with timestamps.

Cache key: the question string (lowercased and stripped). Cache value: the formatted result JSON. Cache TTL: 1 hour (3600 seconds).

Before calling `corrector.execute_with_correction()`, check if the question exists in the cache and was cached within the TTL. If yes, return the cached result directly (add a `cached: true` field to the response to make this visible). If no, proceed normally and store the result in the cache after success.

---

## Phase 14: Observability

### Step 32 — Add Structured Logging

**Library:** Python's built-in `logging` module configured to emit JSON lines. You can also use `structlog` (`uv add structlog`) for more ergonomic structured logging, though the standard library is sufficient.

Create a `src/core/logger.py` module. Configure a logger that formats each log entry as a JSON object with fields: `timestamp`, `level`, `tool`, `question`, `schema_context_length`, `generated_sql`, `validation_result`, `execution_time_ms`, `result_row_count`, `attempts`, `error`.

Update `ask_database` in `server.py` to log these fields at the start and end of each tool invocation. Use log level `INFO` for successful queries and `WARNING` for self-corrected queries, and `ERROR` for complete failures.

---

## Phase 15: Test Suite

### Step 33 — Write Unit Tests

Create test files under `tests/`. Use `pytest` and `pytest-asyncio` (already installed).

**`tests/test_schema_inspector.py`:**
- Fixture: create an in-memory SQLite database with 2-3 tables using SQLAlchemy and `create_engine("sqlite:///:memory:")`
- Test: `get_table_names()` returns the correct table list
- Test: `get_columns()` returns correct column names and types
- Test: `get_foreign_keys()` returns correct FK definitions
- Test: `get_full_schema()` returns a non-empty string containing all table names
- Test: `get_sample_values()` returns a list of actual values from the in-memory DB

**`tests/test_sql_validator.py`:**
- Fixture: create an inspector wrapping an in-memory DB
- Test: `validate("INSERT INTO users VALUES (1)")` returns `is_valid=False`
- Test: `validate("DELETE FROM orders")` returns `is_valid=False`
- Test: `validate("DROP TABLE users")` returns `is_valid=False`
- Test: `validate("SELECT * FROM users")` returns `is_valid=True` with auto-injected LIMIT
- Test: `validate("SELECT COUNT(*) FROM orders GROUP BY status")` returns `is_valid=True` without injecting LIMIT
- Test: `validate("SELECT id FROM nonexistent_table")` returns `is_valid=False` with table-not-found error

**`tests/test_sql_generator.py`:**
- Use `pytest.monkeypatch` or `unittest.mock.AsyncMock` to mock the LLM client
- Test: `generate("how many users?")` calls the LLM with a prompt containing the schema
- Test: strips backticks and markdown code fences from LLM response
- Test: includes dialect keyword in the prompt

**`tests/test_self_corrector.py`:**
- Mock all three pipeline components (generator, validator, executor)
- Test: returns success on first attempt when all steps pass
- Test: retries when executor raises an exception
- Test: calls `_fix_sql` with the error message on each failure
- Test: returns failure dict after `MAX_SELF_CORRECTION_RETRIES` exhausted

**`tests/test_integration.py`:**
- Fixture: spin up an in-memory SQLite DB and seed it with 10-20 rows of test data
- Do NOT mock the LLM for integration tests — use the real Groq API (cheap/free)
- Use a `@pytest.mark.integration` marker and skip these by default (`pytest -m "not integration"` for unit-only runs)
- Test at least 5 natural language questions end-to-end:
  - A simple count query
  - A GROUP BY aggregation
  - A two-table JOIN
  - A filtered query with a WHERE clause
  - A date-based query

### Step 34 — Run and Verify Tests

Run unit tests: `uv run pytest tests/ -m "not integration" -v`

All tests should pass. Fix any failures before proceeding.

Run integration tests (requires real API keys in `.env`): `uv run pytest tests/ -m integration -v`

---

## Phase 16: CI/CD

### Step 35 — Add GitHub Actions CI

Create `.github/workflows/ci.yml` in the project root. This runs on every push and pull request.

**The workflow should:**
1. Trigger on `push` and `pull_request` to `main`
2. Run on `ubuntu-latest`
3. Use `astral-sh/setup-uv@v4` (official uv GitHub Action) to install uv
4. Run `uv sync` to install all dependencies (including dev)
5. Run `uv run ruff check .` for linting
6. Run `uv run ruff format --check .` for formatting check
7. Run `uv run pytest tests/ -m "not integration" -v` for unit tests

Do not run integration tests in CI — they require live API keys and make external API calls. Unit tests should be fully self-contained.

---

## Phase 17: Final Polish

### Step 36 — Add Type Hints

Go through every `.py` file in `src/` and add type hints to all function signatures. Use Python 3.11 type syntax:
- `str | None` instead of `Optional[str]`
- `list[dict]` instead of `List[Dict]`
- Import `from __future__ import annotations` at the top of files if needed

Run `uv run ruff check .` after adding hints — ruff will catch any issues.

### Step 37 — Write the README

Create `README.md` in the project root. It should cover:

1. **What it is** — One paragraph summary
2. **Architecture diagram** — The ASCII diagram from the blueprint
3. **Prerequisites** — Python 3.11+, uv, Node.js (for Inspector), API keys
4. **Quick Start** — Step-by-step from cloning to running in Claude Desktop (5-7 commands)
5. **Configuration** — All `.env` variables explained
6. **Available Tools** — Table with tool name, description, parameters
7. **Self-Correction Loop** — Explain how it works (this is what interviewers will ask about)
8. **Adding Your Own Database** — Just change `DATABASE_URL` in the config
9. **Running Tests** — The pytest commands
10. **Deployment** — Docker compose command for remote HTTP transport

---

## Final Checklist — Before Calling It Done

Go through this checklist before publishing:

- [ ] `uv run python scripts/seed_demo_db.py` creates `demo.db` successfully
- [ ] MCP Inspector shows all 4 tools and 1 resource with correct descriptions
- [ ] All 10 test questions work end-to-end in Claude Desktop with SQLite
- [ ] All 10 test questions work end-to-end in Claude Desktop with PostgreSQL (Docker or Neon)
- [ ] SQL validator blocks `INSERT`, `UPDATE`, `DELETE`, `DROP` queries
- [ ] Self-corrector retries up to 3 times on query failure
- [ ] `uv run pytest tests/ -m "not integration" -v` passes with 0 failures
- [ ] `uv run ruff check .` passes with 0 errors
- [ ] `.env` is in `.gitignore` and never committed
- [ ] `claude_desktop_config.json` in project root has no real API keys
- [ ] `README.md` explains how to connect the server to Claude Desktop
- [ ] `Dockerfile` builds and runs successfully
- [ ] GitHub Actions CI passes on a clean push

---

## Technology Reference Summary

| Component | Library / Tool | Install Command |
|---|---|---|
| MCP Server Runtime | `mcp` (FastMCP) | `uv add mcp` |
| Package Manager | `uv` by Astral | `irm https://astral.sh/uv/install.ps1 \| iex` |
| Database ORM | `sqlalchemy` 2.0 | `uv add sqlalchemy` |
| PostgreSQL Adapter | `psycopg2-binary` | `uv add psycopg2-binary` |
| SQL Safety Parser | `sqlparse` | `uv add sqlparse` |
| Primary LLM SDK | `anthropic` | `uv add anthropic` |
| Fallback LLM SDK | `groq` | `uv add groq` |
| Config Management | `pydantic-settings` | `uv add pydantic-settings` |
| Test Runner | `pytest` | `uv add --dev pytest` |
| Async Test Support | `pytest-asyncio` | `uv add --dev pytest-asyncio` |
| Linter + Formatter | `ruff` | `uv add --dev ruff` |
| Server Debugger | MCP Inspector (npm) | `npx @modelcontextprotocol/inspector` |
| PostgreSQL (local) | Docker `postgres:16` | `docker run postgres:16` |
| PostgreSQL (cloud) | Neon.tech | Sign up at neon.tech |
| CI | GitHub Actions + `astral-sh/setup-uv@v4` | `.github/workflows/ci.yml` |
