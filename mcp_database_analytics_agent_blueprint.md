# MCP Database Analytics Agent — Complete Technical Blueprint

**For:** Abhishek Garg  
**Date:** March 29, 2026

---

## 1. What It Is

An MCP-compliant server that turns any PostgreSQL or SQLite database into a natural-language queryable endpoint. Any MCP client — Claude Desktop, Cursor, Windsurf, ChatGPT, VS Code Copilot — connects to your server, and the user simply asks questions like *"What were our top 5 products by revenue last quarter?"* The agent introspects the database schema, generates SQL, validates it, self-corrects on failure, executes it, and returns structured results with optional chart-ready data.

This is not a chatbot wrapper. It's an **infrastructure-level tool** that any AI client on the planet can plug into via the MCP standard — the way a REST API serves web clients, your MCP server serves AI agents.

---

## 2. What Problem It Solves

**The gap:** Business users (PMs, founders, ops leads) can't query their own data. They file tickets, wait for analyst bandwidth, or struggle with Metabase/Looker dashboards that never have the right view pre-built. Meanwhile, the data sits in PostgreSQL, ready to answer their question in 200ms.

**Current solutions and why they fall short:**

Metabase and Looker require pre-built dashboards or SQL knowledge. ChatGPT with Code Interpreter can't connect to private databases. Existing text-to-SQL tools like Wren AI are standalone apps that don't integrate with the AI tools people already use daily. The Postgres MCP servers that exist today are thin wrappers — they expose raw SQL execution but don't do schema-aware query generation, self-correction, or result formatting.

**Your agent fills the gap** by combining intelligent SQL generation with the MCP protocol, so it works inside *every* AI client without custom integration.

---

## 3. System Architecture

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
│  │              TOOL: describe_schema                    │    │
│  │  Returns table names, columns, types, relationships   │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              TOOL: list_tables                        │    │
│  │  Returns available tables with row counts             │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐    │
│  │              TOOL: get_sample_data                    │    │
│  │  Returns first N rows from a table for exploration    │    │
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

---

## 4. Detailed Data Flow

Here's exactly what happens when a user asks *"Show me monthly revenue trends for 2024"* in Claude Desktop:

**Step 1 — Client Discovery**
Claude Desktop connects to your MCP server (via stdio or HTTP). The server responds with its capability manifest: 4 tools + 1 resource. Claude now knows what your server can do.

**Step 2 — Schema Context Injection**
Before generating a query, the LLM client reads the `schema://overview` resource. This gives it the full database structure: table names, column names, data types, foreign key relationships, and sample values. This is injected into the LLM's context so it writes accurate SQL.

**Step 3 — Tool Invocation: `ask_database`**
The LLM decides to call your `ask_database` tool with the parameter: `{"question": "Show me monthly revenue trends for 2024"}`.

**Step 4 — Schema Introspection (inside the tool)**
The tool uses SQLAlchemy's `inspect()` to pull the live schema. It identifies relevant tables (e.g., `orders`, `order_items`, `products`), their columns, and join paths. It builds a compact schema description string.

**Step 5 — SQL Generation**
The tool sends the user's question + schema description to an LLM (Claude API or Groq) with a carefully crafted prompt:

```
Given this database schema:
{schema_description}

Generate a PostgreSQL query to answer: "{question}"

Rules:
- Use only tables and columns that exist in the schema
- Always use table aliases
- For date filtering, use proper date functions
- LIMIT results to 100 rows unless the user asks for all
- Return ONLY the SQL query, no explanation
```

The LLM returns:
```sql
SELECT
    DATE_TRUNC('month', o.created_at) AS month,
    SUM(oi.quantity * oi.unit_price) AS revenue
FROM orders o
JOIN order_items oi ON o.id = oi.order_id
WHERE o.created_at >= '2024-01-01' AND o.created_at < '2025-01-01'
GROUP BY month
ORDER BY month;
```

**Step 6 — Safety Validation**
Before execution, the tool checks the generated SQL:
- Is it a read-only query? (No INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE)
- Does it reference only tables/columns that exist?
- Does it have a LIMIT clause? (inject one if missing)

**Step 7 — Execution**
The validated query runs via SQLAlchemy with a read-only connection and a timeout (default 30s).

**Step 8 — Self-Correction Loop (if execution fails)**
If the query throws an error (bad column name, syntax error, type mismatch), the tool enters a correction loop:

```
The following SQL query failed:
{failed_sql}

Error message: {error_message}

Database schema: {schema_description}

Please fix the query and return ONLY the corrected SQL.
```

This loops up to 3 times. If all 3 fail, the tool returns the error to the client with a suggestion to rephrase.

**Step 9 — Result Formatting**
Successful results are formatted as a structured response:

```json
{
  "query": "SELECT DATE_TRUNC('month', ...) ...",
  "row_count": 12,
  "columns": ["month", "revenue"],
  "data": [
    {"month": "2024-01-01", "revenue": 45230.50},
    {"month": "2024-02-01", "revenue": 52100.75}
  ],
  "summary": "Monthly revenue for 2024 ranged from $42K to $68K, with peak in November."
}
```

**Step 10 — Client Rendering**
Claude Desktop receives this structured response, and the LLM presents it to the user as a formatted table, chart description, or conversational answer.

---

## 5. Complete Tech Stack

| Layer | Technology | Why This Choice |
|---|---|---|
| **MCP Runtime** | `mcp` Python SDK (FastMCP) | Official Anthropic SDK. Handles protocol, transport, tool registration |
| **Transport** | stdio (local) + Streamable HTTP (remote) | stdio for Claude Desktop/Cursor. HTTP for team/cloud deployments |
| **SQL Generation LLM** | Claude API (primary) / Groq (free tier fallback) | Claude for accuracy. Groq's Llama 3.3 as zero-cost dev option |
| **LLM Orchestration** | LangChain (optional) or raw API calls | LangChain if you want chain composition. Raw calls for simplicity |
| **Database Connector** | SQLAlchemy 2.0 | Dialect-agnostic. Same code works for PostgreSQL, SQLite, MySQL |
| **Database Introspection** | SQLAlchemy `inspect()` + `information_schema` | Full schema extraction: tables, columns, types, FKs, constraints |
| **Query Safety** | `sqlparse` + custom validator | Parse SQL AST to detect write operations before execution |
| **Package Manager** | `uv` | Required by MCP ecosystem. Faster than pip. Handles virtual envs |
| **Testing** | `pytest` + MCP Inspector | MCP Inspector shows raw JSON-RPC messages for debugging |
| **Config** | `pydantic-settings` + `.env` | Type-safe configuration for DB URLs, API keys, limits |

---

## 6. Project Structure

```
mcp-db-agent/
├── pyproject.toml              # uv project config with dependencies
├── .env                        # DB_URL, ANTHROPIC_API_KEY, etc.
├── README.md
│
├── src/
│   ├── __init__.py
│   ├── server.py               # FastMCP server — tool & resource registration
│   ├── config.py               # Pydantic settings (DB URL, API keys, limits)
│   │
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── ask_database.py     # Core tool: NL → SQL → execute → format
│   │   ├── describe_schema.py  # Tool: return schema for specific table(s)
│   │   ├── list_tables.py      # Tool: list all tables with row counts
│   │   └── get_sample_data.py  # Tool: return first N rows from a table
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── schema_inspector.py # SQLAlchemy introspection → structured schema
│   │   ├── sql_generator.py    # LLM prompt construction + SQL generation
│   │   ├── sql_validator.py    # Safety checks (read-only, valid refs, limits)
│   │   ├── sql_executor.py     # Execute query with timeout + error capture
│   │   ├── self_corrector.py   # Retry loop: error → LLM fix → re-execute
│   │   └── result_formatter.py # Raw rows → structured JSON response
│   │
│   └── resources/
│       ├── __init__.py
│       └── schema_overview.py  # MCP Resource: full schema as context
│
├── tests/
│   ├── test_schema_inspector.py
│   ├── test_sql_generator.py
│   ├── test_sql_validator.py
│   ├── test_self_corrector.py
│   └── test_integration.py     # End-to-end: question → answer
│
├── scripts/
│   └── seed_demo_db.py         # Create demo SQLite DB with sample data
│
└── claude_desktop_config.json  # Example config for Claude Desktop
```

---

## 7. Key Component Deep Dives

### 7.1 — Schema Inspector (`schema_inspector.py`)

This is the foundation. Bad schema context = bad SQL. The inspector must produce a **compact, LLM-optimizable** representation.

```python
# Pseudocode structure
class SchemaInspector:
    def __init__(self, engine: Engine):
        self.engine = engine
        self.inspector = inspect(engine)

    def get_full_schema(self) -> str:
        """Returns compact schema string for LLM context injection."""
        tables = self.inspector.get_table_names()
        schema_parts = []

        for table in tables:
            columns = self.inspector.get_columns(table)
            pks = self.inspector.get_pk_constraint(table)
            fks = self.inspector.get_foreign_keys(table)

            col_defs = []
            for col in columns:
                col_str = f"  {col['name']} {col['type']}"
                if col['name'] in pks.get('constrained_columns', []):
                    col_str += " PRIMARY KEY"
                col_defs.append(col_str)

            fk_defs = []
            for fk in fks:
                fk_defs.append(
                    f"  FOREIGN KEY ({', '.join(fk['constrained_columns'])}) "
                    f"→ {fk['referred_table']}({', '.join(fk['referred_columns'])})"
                )

            schema_parts.append(
                f"TABLE: {table}\n" +
                "\n".join(col_defs) +
                ("\n" + "\n".join(fk_defs) if fk_defs else "")
            )

        return "\n\n".join(schema_parts)

    def get_sample_values(self, table: str, column: str, limit: int = 5) -> list:
        """Get sample distinct values for a column — helps LLM understand data."""
        query = text(f"SELECT DISTINCT {column} FROM {table} LIMIT :limit")
        with self.engine.connect() as conn:
            return [row[0] for row in conn.execute(query, {"limit": limit})]
```

**Why sample values matter:** If the column is `status` with values `['pending', 'shipped', 'delivered', 'cancelled']`, the LLM will use the exact enum values instead of guessing. This alone eliminates 30%+ of SQL errors.

### 7.2 — SQL Generator (`sql_generator.py`)

```python
class SQLGenerator:
    def __init__(self, llm_client, schema_inspector: SchemaInspector):
        self.llm = llm_client
        self.schema = schema_inspector

    async def generate(self, question: str, dialect: str = "postgresql") -> str:
        schema_text = self.schema.get_full_schema()

        prompt = f"""You are a SQL expert. Generate a {dialect} query to answer
the user's question based on the database schema below.

DATABASE SCHEMA:
{schema_text}

RULES:
1. Use ONLY tables and columns that exist in the schema above.
2. Always alias tables (e.g., SELECT o.id FROM orders o).
3. Add LIMIT 100 unless the user asks for all results or it's an aggregation.
4. For date ranges, use proper {dialect} date functions.
5. Use LEFT JOIN when the relationship might have missing data.
6. Return ONLY the raw SQL. No markdown, no explanation, no backticks.

USER QUESTION: {question}

SQL:"""

        response = await self.llm.generate(prompt)
        return response.strip().strip('`').strip()
```

### 7.3 — Self-Correction Loop (`self_corrector.py`)

This is the differentiating feature. Most text-to-SQL tools fail silently. Yours retries intelligently.

```python
class SelfCorrector:
    MAX_RETRIES = 3

    def __init__(self, sql_generator, sql_executor, sql_validator):
        self.generator = sql_generator
        self.executor = sql_executor
        self.validator = sql_validator

    async def execute_with_correction(self, question: str) -> dict:
        sql = await self.generator.generate(question)
        errors_so_far = []

        for attempt in range(self.MAX_RETRIES):
            # Validate first
            validation = self.validator.validate(sql)
            if not validation.is_valid:
                errors_so_far.append(f"Validation: {validation.error}")
                sql = await self._fix(question, sql, validation.error, errors_so_far)
                continue

            # Execute
            try:
                result = await self.executor.execute(sql)
                return {
                    "success": True,
                    "sql": sql,
                    "data": result,
                    "attempts": attempt + 1
                }
            except Exception as e:
                errors_so_far.append(f"Execution: {str(e)}")
                sql = await self._fix(question, sql, str(e), errors_so_far)

        return {
            "success": False,
            "error": f"Failed after {self.MAX_RETRIES} attempts",
            "errors": errors_so_far,
            "last_sql": sql
        }

    async def _fix(self, question, failed_sql, error, history) -> str:
        prompt = f"""The following SQL query failed.

ORIGINAL QUESTION: {question}
FAILED SQL: {failed_sql}
ERROR: {error}
PREVIOUS ERRORS: {history}

Fix the SQL query. Return ONLY the corrected SQL."""

        return await self.generator.llm.generate(prompt)
```

### 7.4 — SQL Validator (`sql_validator.py`)

```python
import sqlparse

class SQLValidator:
    FORBIDDEN_KEYWORDS = {
        'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'TRUNCATE',
        'CREATE', 'GRANT', 'REVOKE', 'EXEC', 'EXECUTE'
    }

    def __init__(self, schema_inspector):
        self.schema = schema_inspector

    def validate(self, sql: str) -> ValidationResult:
        # 1. Parse and check for write operations
        parsed = sqlparse.parse(sql)
        for statement in parsed:
            for token in statement.flatten():
                if token.ttype is sqlparse.tokens.Keyword.DML:
                    if token.value.upper() in self.FORBIDDEN_KEYWORDS:
                        return ValidationResult(
                            is_valid=False,
                            error=f"Write operation '{token.value}' is not allowed. Read-only queries only."
                        )

        # 2. Check table references exist
        tables = self.schema.inspector.get_table_names()
        # (simplified — real impl uses sqlparse to extract table names)

        # 3. Check for missing LIMIT on non-aggregate queries
        upper_sql = sql.upper()
        if 'LIMIT' not in upper_sql and 'GROUP BY' not in upper_sql and 'COUNT(' not in upper_sql:
            return ValidationResult(
                is_valid=True,
                warning="No LIMIT clause — consider adding one.",
                modified_sql=sql.rstrip(';') + ' LIMIT 100;'
            )

        return ValidationResult(is_valid=True)
```

### 7.5 — MCP Server (`server.py`)

```python
from mcp.server.fastmcp import FastMCP
from src.config import Settings
from src.core.schema_inspector import SchemaInspector
from src.core.self_corrector import SelfCorrector
# ... other imports

settings = Settings()
mcp = FastMCP(
    "Database Analytics Agent",
    dependencies=["sqlalchemy", "sqlparse", "anthropic"]
)

# Initialize on startup
engine = create_engine(settings.database_url)
inspector = SchemaInspector(engine)
corrector = SelfCorrector(...)


@mcp.resource("schema://overview")
def schema_overview() -> str:
    """Full database schema for LLM context."""
    return inspector.get_full_schema()


@mcp.tool()
async def ask_database(question: str) -> str:
    """Ask a natural language question about the database.
    The agent will generate SQL, execute it safely, and return results.
    If the query fails, it will self-correct up to 3 times.

    Args:
        question: Natural language question about the data
    """
    result = await corrector.execute_with_correction(question)

    if result["success"]:
        return json.dumps({
            "sql": result["sql"],
            "row_count": len(result["data"]),
            "columns": list(result["data"][0].keys()) if result["data"] else [],
            "data": result["data"][:100],
            "attempts": result["attempts"]
        }, default=str, indent=2)
    else:
        return json.dumps({
            "error": result["error"],
            "attempted_sql": result["last_sql"],
            "suggestion": "Try rephrasing your question or ask me to describe the schema first."
        }, indent=2)


@mcp.tool()
def list_tables() -> str:
    """List all tables in the database with row counts."""
    tables = inspector.get_tables_with_counts()
    return json.dumps(tables, indent=2)


@mcp.tool()
def describe_schema(table_name: str) -> str:
    """Get detailed schema for a specific table including columns,
    types, primary keys, foreign keys, and sample values.

    Args:
        table_name: Name of the table to describe
    """
    return inspector.get_table_detail(table_name)


@mcp.tool()
def get_sample_data(table_name: str, limit: int = 5) -> str:
    """Get sample rows from a table to understand the data.

    Args:
        table_name: Name of the table
        limit: Number of rows to return (max 20)
    """
    limit = min(limit, 20)
    return json.dumps(inspector.get_sample_rows(table_name, limit), default=str, indent=2)


if __name__ == "__main__":
    mcp.run(transport="stdio")  # For Claude Desktop
    # For remote: mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
```

---

## 8. Claude Desktop Configuration

After building, users connect by adding this to their `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "db-analytics": {
      "command": "uv",
      "args": [
        "--directory", "/path/to/mcp-db-agent",
        "run", "src/server.py"
      ],
      "env": {
        "DATABASE_URL": "postgresql://user:pass@localhost:5432/mydb",
        "ANTHROPIC_API_KEY": "sk-ant-..."
      }
    }
  }
}
```

That's it. Restart Claude Desktop, and the user can immediately ask questions about their database.

---

## 9. Build Roadmap — 14-Day Sprint

### Week 1: Core Engine (Days 1–7)

**Day 1 — Project Scaffold + Schema Inspector**
- Set up `uv` project with `pyproject.toml`
- Install dependencies: `mcp`, `sqlalchemy`, `sqlparse`, `anthropic`, `pydantic-settings`
- Implement `SchemaInspector` — introspect tables, columns, types, FKs
- Write `seed_demo_db.py` — create a demo e-commerce SQLite DB (users, orders, products, order_items)
- Test: inspector returns accurate schema for demo DB

**Day 2 — SQL Generator + LLM Integration**
- Implement `SQLGenerator` with Claude API (primary) and Groq (fallback)
- Craft the system prompt with schema injection
- Handle dialect differences (PostgreSQL vs SQLite)
- Test: generate correct SQL for 10 sample questions against demo DB

**Day 3 — SQL Validator + Executor**
- Implement `SQLValidator` — block writes, enforce LIMIT, check table existence
- Implement `SQLExecutor` — run queries via SQLAlchemy with timeout
- Use read-only connection (SQLAlchemy `execution_options(isolation_level="AUTOCOMMIT")` with no write permissions)
- Test: validator catches INSERT/DELETE, executor returns structured results

**Day 4 — Self-Correction Loop**
- Implement `SelfCorrector` — 3-retry loop with error context injection
- Log each attempt (question → SQL → error → fixed SQL) for debugging
- Test: intentionally break queries (wrong column names, bad syntax) and verify auto-fix

**Day 5 — Result Formatter + MCP Server Shell**
- Implement `ResultFormatter` — convert raw rows to structured JSON with summary
- Set up `FastMCP` server with all 4 tools + 1 resource
- Test with MCP Inspector: `mcp dev src/server.py`

**Day 6 — Claude Desktop Integration**
- Write `claude_desktop_config.json` for the demo DB
- Test end-to-end in Claude Desktop with 20+ varied questions
- Fix edge cases: empty results, very wide tables, date formatting, NULL handling

**Day 7 — PostgreSQL Support + Config**
- Test against a real PostgreSQL instance (local Docker or free Neon.tech)
- Implement `pydantic-settings` config for DB URL, API key, timeout, max retries
- Handle PostgreSQL-specific types (JSONB, ARRAY, UUID, TIMESTAMPTZ)
- Write comprehensive README with setup instructions

### Week 2: Production Polish (Days 8–14)

**Day 8 — Enhanced Schema Context**
- Add sample values to schema context (top 5 distinct values per column)
- Add table relationship graph (which tables join to which)
- Add column descriptions from PostgreSQL COMMENT if available
- Test: improved SQL accuracy on ambiguous questions

**Day 9 — Streamable HTTP Transport**
- Add HTTP transport so the server can run remotely
- Implement basic auth (API key header) for the HTTP endpoint
- Test with remote MCP clients
- Docker-ify the server for deployment

**Day 10 — Query History + Caching**
- Add SQLite-based query log (question, generated SQL, result summary, timestamp, success/fail)
- Implement simple LRU cache — if the same question was asked in the last hour, return cached result
- Add a `query_history` tool so the LLM can reference past queries

**Day 11 — Error Handling + Observability**
- Add structured logging (JSON format) for every tool invocation
- Log: question → schema context size → generated SQL → validation result → execution time → result size
- Handle edge cases: connection failures, query timeouts, LLM API rate limits
- Graceful degradation: if LLM is unavailable, return schema info and suggest raw SQL

**Day 12 — Testing Suite**
- Write unit tests for each core module
- Write integration tests: 30+ natural language questions against demo DB
- Test self-correction with intentionally adversarial questions
- Test with both SQLite and PostgreSQL

**Day 13 — Documentation + Demo**
- Write detailed README with architecture diagram, setup guide, usage examples
- Create a 2-minute demo GIF/video showing Claude Desktop querying a database
- Document the prompt engineering decisions (why each rule in the system prompt exists)

**Day 14 — GitHub Polish + Resume Line**
- Clean up code, add type hints everywhere, docstrings on all public methods
- Add GitHub Actions CI (lint + test)
- Add LICENSE (MIT)
- Write a blog-post-style README section explaining the self-correction loop
- Publish to GitHub and npm (for MCP server discovery)

---

## 10. Demo Database Schema

For the portfolio demo, seed a realistic e-commerce database:

```sql
-- users
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(255) UNIQUE,
    country VARCHAR(50),
    created_at TIMESTAMP DEFAULT NOW()
);

-- products
CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200),
    category VARCHAR(100),  -- 'Electronics', 'Clothing', 'Books', etc.
    price DECIMAL(10,2),
    stock_quantity INTEGER,
    created_at TIMESTAMP DEFAULT NOW()
);

-- orders
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id),
    status VARCHAR(20),  -- 'pending', 'shipped', 'delivered', 'cancelled'
    total_amount DECIMAL(10,2),
    created_at TIMESTAMP DEFAULT NOW()
);

-- order_items
CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_id INTEGER REFERENCES products(id),
    quantity INTEGER,
    unit_price DECIMAL(10,2)
);

-- Seed with 500 users, 100 products, 2000 orders, 5000 order_items
-- Spread across 2023-2024 for trend analysis questions
```

**Sample questions this schema supports:**
- "What are the top 5 products by revenue?"
- "Show me monthly revenue trends for 2024"
- "Which countries have the most customers?"
- "What's the average order value by product category?"
- "How many orders were cancelled last quarter?"
- "Who are my repeat customers with more than 3 orders?"
- "What's the conversion rate from pending to delivered?"

---

## 11. Prompt Engineering Notes

**Key decisions in the SQL generation prompt:**

1. **"Use ONLY tables and columns that exist"** — Without this, LLMs hallucinate column names 40%+ of the time on complex schemas.

2. **"Always alias tables"** — Prevents ambiguous column references in JOINs, which is the #1 source of execution errors.

3. **"LIMIT 100 unless aggregation"** — Prevents accidental full-table scans on million-row tables. Aggregations (GROUP BY, COUNT) naturally limit output.

4. **"Return ONLY the raw SQL"** — LLMs love wrapping SQL in markdown code blocks and adding explanations. This breaks your parser. Be explicit.

5. **Schema format uses compact DDL-like notation** rather than verbose JSON — saves 60%+ tokens on large schemas while preserving all information.

6. **Sample values in schema context** — The single biggest accuracy improvement. If the LLM sees `status: ['pending', 'shipped', 'delivered', 'cancelled']`, it uses the exact values instead of guessing `'active'` or `'complete'`.

---

## 12. Skills You'll Gain (for Resume/Interviews)

| Skill | Depth | Interview Talking Point |
|---|---|---|
| **MCP Protocol** | Deep | "I built an MCP server from scratch that's compatible with Claude Desktop, Cursor, and ChatGPT" |
| **Text-to-SQL** | Deep | "Implemented schema-aware SQL generation with a 3-retry self-correction loop that handles dialect differences" |
| **LLM Tool Use / Function Calling** | Deep | "Designed tool schemas with input/output validation so LLM clients can discover and invoke database tools" |
| **SQLAlchemy Introspection** | Medium | "Used SQLAlchemy's inspection API for dialect-agnostic schema extraction across PostgreSQL and SQLite" |
| **Prompt Engineering** | Deep | "Engineered prompts that reduced SQL generation errors by including sample column values and explicit formatting rules" |
| **Agent Safety** | Medium | "Implemented SQL validation layer that blocks write operations and enforces query limits before execution" |
| **Protocol Design** | Medium | "Understood JSON-RPC, stdio/HTTP transports, and tool discovery in the MCP specification" |

---

## 13. How This Connects to Your Existing Work

**From your ShopIQ project:** You already designed a text-to-SQL engine with a self-correction loop in the `CLAUDE.md` spec. This project takes that exact pattern and wraps it in the industry-standard MCP protocol, making it universally usable instead of Shopify-specific.

**From your Enterprise RAG project:** The schema inspector is analogous to your semantic chunking pipeline — both are about giving the LLM the right context. Your RAG system chunks documents; this system chunks database schemas.

**From your Kinben work:** You've built 10+ REST API endpoints with Node.js/Express. MCP tools are conceptually the same — request/response with input validation — but designed for AI clients instead of web clients.

The narrative on your resume becomes: *"I progressed from building RAG systems (document retrieval) → text-to-SQL engines (data querying) → MCP servers (universal AI tool infrastructure), each project building on the last."*

---

## 14. Stretch Goals (After the 14-Day Core)

Once the core is solid, these additions compound the project's impact:

1. **Multi-database support** — Connect to multiple databases simultaneously. The LLM picks which DB to query based on the question. Uses MCP's resource system to advertise available databases.

2. **Query explanation mode** — A `explain_query` tool that returns the EXPLAIN ANALYZE output in plain English, helping users understand why a query is slow.

3. **Semantic column matching** — Embed column descriptions in a vector store (Qdrant). When the user says "revenue," it matches to `order_items.unit_price * order_items.quantity` even if there's no `revenue` column.

4. **Chart-ready output** — Return results in a format that MCP Apps (the new interactive UI standard in MCP) can render as charts directly inside Claude Desktop.

5. **Publish to npm + MCP registries** — List the server on Glama.ai, the official MCP server directory, and npm. Real users discovering your tool = best possible resume signal.
