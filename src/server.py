"""MCP server entrypoint — wires all pipeline components and registers tools/resources."""

import json
import logging
import sys
import time
from pathlib import Path

# When executed as a script (`uv run src/server.py`), Python adds `src/` to
# sys.path but NOT the project root.  The absolute `src.*` imports below
# require the project root on sys.path, so we insert it before they resolve.
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine

from src.config import settings
from src.core.logger import get_logger
from src.core.result_formatter import ResultFormatter
from src.core.schema_inspector import SchemaInspector
from src.core.self_corrector import SelfCorrector
from src.core.sql_executor import SQLExecutor
from src.core.sql_generator import SQLGenerator
from src.core.sql_validator import SQLValidator
from src.core.query_log import QueryLog
from src.resources.schema_overview import get_schema_overview

# Import tool implementations under private aliases so the public names below
# can be used as the MCP-visible tool names without shadowing the imports.
from src.tools.describe_schema import describe_schema as _describe_schema
from src.tools.get_sample_data import get_sample_data as _get_sample_data
from src.tools.list_tables import list_tables as _list_tables

# ---------------------------------------------------------------------------
# Bootstrap — engine and pipeline components (shared across all requests)
# ---------------------------------------------------------------------------

engine = create_engine(settings.database_url)

inspector = SchemaInspector(engine)
generator = SQLGenerator(settings, inspector)
validator = SQLValidator(inspector)
executor = SQLExecutor(engine, settings)
corrector = SelfCorrector(generator, validator, executor, settings)
formatter = ResultFormatter()
query_log = QueryLog()

# Derive the SQL dialect once at startup so every ask_database call uses the
# right date functions and syntax for the configured database.
dialect: str = "postgresql" if settings.database_url.startswith("postgresql") else "sqlite"

# ---------------------------------------------------------------------------
# In-memory LRU cache for repeated identical questions
# ---------------------------------------------------------------------------

# Maps lowercased+stripped question → (formatted_json_result, monotonic_timestamp)
_cache: dict[str, tuple[str, float]] = {}
CACHE_TTL = 3600  # seconds

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP("Database Analytics Agent")
_log = get_logger()

# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


@mcp.resource("schema://overview")
def schema_overview() -> str:
    """Full database schema in compact DDL-like notation.

    Fetch this resource to inject the complete table and column definitions
    into your context before writing a query. It covers every table, column
    type, primary key, and foreign key relationship — equivalent to calling
    describe_schema on every table at once but faster.
    """
    return get_schema_overview(inspector)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_tables() -> str:
    """List all tables in the database with their row counts.

    Returns a JSON array where each element has ``table_name`` (str) and
    ``row_count`` (int). Call this first to discover what data is available
    before running a query or describing a specific table.
    """
    return _list_tables(inspector)


@mcp.tool()
def describe_schema(table_name: str) -> str:
    """Describe the columns, primary keys, foreign keys, and sample values for a table.

    Returns a formatted string with full column metadata — type, nullability,
    whether it is a primary key — plus a few sampled values per column so you
    can see what the data actually looks like before writing a query.

    Call list_tables first if you are unsure which tables exist.

    Args:
        table_name: Name of the table to describe.
    """
    return _describe_schema(table_name, inspector)


@mcp.tool()
def get_sample_data(table_name: str, limit: int = 5) -> str:
    """Get sample rows from a table to understand the data format and values.

    Returns a JSON array of row objects. The limit is clamped to [1, 20];
    use ask_database for larger result sets.

    Call list_tables first if you are unsure which tables exist.

    Args:
        table_name: Name of the table to sample.
        limit: Number of rows to return (1–20). Defaults to 5.
    """
    return _get_sample_data(table_name, inspector, limit)


@mcp.tool()
async def ask_database(question: str) -> str:
    """Ask a natural-language question about the database.

    The agent translates your question into SQL, validates it for safety
    (no writes allowed), executes it, and returns structured JSON results.
    If the generated SQL fails, it automatically retries with LLM-assisted
    self-correction up to three times before reporting failure.

    Returns a JSON object with:
    - ``query``: the SQL that was executed
    - ``row_count``: total number of rows returned
    - ``columns``: list of column names
    - ``data``: list of row dicts (capped at 100)
    - ``attempts``: number of generation/correction cycles used
    - ``cached``: present and ``true`` only when the result came from cache

    On failure:
    - ``error``: final error message
    - ``attempted_sql``: last SQL that was tried
    - ``errors``: full list of errors from each retry
    - ``suggestion``: hint for how to proceed

    Args:
        question: Plain-English question about the data, e.g.
                  "How many orders were placed in 2024?" or
                  "List the top 5 products by revenue."
    """
    cache_key = question.lower().strip()
    now = time.monotonic()
    schema_context_length = len(generator.get_schema_context())

    _log.info(
        "ask_database",
        extra={
            "fields": {
                "tool": "ask_database",
                "event": "started",
                "question": question,
                "schema_context_length": schema_context_length,
            }
        },
    )

    # --- Cache hit ---
    if cache_key in _cache:
        cached_result, cached_at = _cache[cache_key]
        if now - cached_at < CACHE_TTL:
            payload = json.loads(cached_result)
            payload["cached"] = True
            _log.info(
                "ask_database",
                extra={
                    "fields": {
                        "tool": "ask_database",
                        "event": "completed",
                        "question": question,
                        "schema_context_length": schema_context_length,
                        "generated_sql": payload.get("query"),
                        "validation_result": "passed",
                        "execution_time_ms": 0,
                        "result_row_count": payload.get("row_count", 0),
                        "attempts": payload.get("attempts", 1),
                        "error": None,
                        "cached": True,
                    }
                },
            )
            return json.dumps(payload, indent=2)

    # --- Execute pipeline ---
    start = time.monotonic()
    result = await corrector.execute_with_correction(question, dialect)
    duration_ms = int((time.monotonic() - start) * 1000)

    if result["success"]:
        formatted = formatter.format(result["sql"], result["data"], result["attempts"])
        query_log.log_query(
            question=question,
            sql=result["sql"],
            success=True,
            row_count=len(result["data"]),
            attempts=result["attempts"],
            duration_ms=duration_ms,
            error=None,
        )
        _cache[cache_key] = (formatted, time.monotonic())
        log_level = logging.WARNING if result["attempts"] > 1 else logging.INFO
        _log.log(
            log_level,
            "ask_database",
            extra={
                "fields": {
                    "tool": "ask_database",
                    "event": "completed",
                    "question": question,
                    "schema_context_length": schema_context_length,
                    "generated_sql": result["sql"],
                    "validation_result": "passed",
                    "execution_time_ms": duration_ms,
                    "result_row_count": len(result["data"]),
                    "attempts": result["attempts"],
                    "error": None,
                }
            },
        )
        return formatted

    last_error = result["errors"][-1] if result["errors"] else "Query failed after maximum retries"
    formatted = formatter.format_error(last_error, result["sql"], result["errors"])
    query_log.log_query(
        question=question,
        sql=result["sql"],
        success=False,
        row_count=0,
        attempts=result["attempts"],
        duration_ms=duration_ms,
        error=last_error,
    )
    _log.error(
        "ask_database",
        extra={
            "fields": {
                "tool": "ask_database",
                "event": "completed",
                "question": question,
                "schema_context_length": schema_context_length,
                "generated_sql": result["sql"],
                "validation_result": "failed",
                "execution_time_ms": duration_ms,
                "result_row_count": 0,
                "attempts": result["attempts"],
                "error": last_error,
            }
        },
    )
    return formatted


@mcp.tool()
def query_history(limit: int = 10) -> str:
    """See recent questions asked to the database, the SQL generated, and whether they succeeded.

    Returns a JSON array of the last N queries (default 10), newest first.
    Each entry has:
    - ``question``: the original natural-language question
    - ``sql``: the SQL that was executed
    - ``success``: whether the query succeeded
    - ``row_count``: number of rows returned (0 on failure)
    - ``attempts``: number of generation/correction cycles used
    - ``duration_ms``: total pipeline wall-clock time in milliseconds
    - ``error``: error message if the query failed, otherwise ``null``
    - ``timestamp``: UTC timestamp of the query

    Args:
        limit: Number of recent queries to return (default 10).
    """
    return json.dumps(query_log.get_recent_queries(limit), indent=2)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if settings.transport == "streamable-http":
        mcp.run(transport="streamable-http", host="0.0.0.0", port=8000)
    else:
        mcp.run(transport="stdio")
