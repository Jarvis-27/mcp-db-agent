"""MCP server entrypoint — wires all pipeline components and registers tools/resources.

Supports two modes:
- **Single-tenant** (default): One DATABASE_URL in .env, works exactly like before.
- **Multi-tenant** (MULTI_TENANT=true): Each request carries an api_key that is
  resolved to a database URL via the tenant registry.  Engines are pooled and
  reused across requests.
"""

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
# Multi-tenant components (only initialised when MULTI_TENANT=true)
# ---------------------------------------------------------------------------

_engine_pool = None  # EnginePool | None
_tenant_registry = None  # TenantRegistry | None

if settings.multi_tenant:
    from src.core.engine_pool import EnginePool
    from src.core.tenant_registry import TenantRegistry

    _engine_pool = EnginePool(
        max_size=settings.engine_pool_max_size,
        max_idle_seconds=settings.engine_pool_idle_seconds,
    )
    _tenant_registry = TenantRegistry()

# ---------------------------------------------------------------------------
# Single-tenant bootstrap (shared across all requests — the original path)
# ---------------------------------------------------------------------------

_single_engine = None  # Engine | None
_single_inspector = None  # SchemaInspector | None
_single_generator = None  # SQLGenerator | None
_single_validator = None  # SQLValidator | None
_single_executor = None  # SQLExecutor | None
_single_corrector = None  # SelfCorrector | None
_single_dialect = "sqlite"

if not settings.multi_tenant:
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is required in single-tenant mode")
    _single_engine = create_engine(settings.database_url)
    _single_inspector = SchemaInspector(_single_engine)
    _single_generator = SQLGenerator(settings, _single_inspector)
    _single_validator = SQLValidator(_single_inspector)
    _single_executor = SQLExecutor(_single_engine, settings)
    _single_corrector = SelfCorrector(
        _single_generator, _single_validator, _single_executor, settings
    )
    _single_dialect = "postgresql" if settings.database_url.startswith("postgresql") else "sqlite"

formatter = ResultFormatter()
query_log = QueryLog()

# ---------------------------------------------------------------------------
# Tenant resolution helper
# ---------------------------------------------------------------------------


def _resolve_tenant(
    api_key: str | None,
) -> tuple[SchemaInspector, SQLGenerator, SQLValidator, SQLExecutor, SelfCorrector, str]:
    """Return pipeline components for the given API key.

    In single-tenant mode, api_key is ignored and the shared components are
    returned.  In multi-tenant mode, the api_key is resolved via the tenant
    registry and an engine is fetched from the pool.
    """
    if not settings.multi_tenant:
        assert (
            _single_inspector
            and _single_generator
            and _single_validator
            and _single_executor
            and _single_corrector
        )
        return (
            _single_inspector,
            _single_generator,
            _single_validator,
            _single_executor,
            _single_corrector,
            _single_dialect,
        )

    if not api_key:
        raise ValueError("api_key is required in multi-tenant mode")

    assert _tenant_registry and _engine_pool
    database_url = _tenant_registry.resolve(api_key)
    if not database_url:
        raise ValueError("Invalid or inactive API key")

    engine = _engine_pool.get(database_url)
    dialect = "postgresql" if database_url.startswith("postgresql") else "sqlite"

    inspector = SchemaInspector(engine)
    generator = SQLGenerator(settings, inspector)
    validator = SQLValidator(inspector)
    executor = SQLExecutor(engine, settings)
    corrector = SelfCorrector(generator, validator, executor, settings)
    return inspector, generator, validator, executor, corrector, dialect


# ---------------------------------------------------------------------------
# In-memory LRU cache for repeated identical questions
# ---------------------------------------------------------------------------

# Maps (api_key_or_none, lowercased_question) → (formatted_json_result, monotonic_timestamp)
_cache: dict[tuple[str | None, str], tuple[str, float]] = {}
CACHE_TTL = 3600  # seconds

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "Database Analytics Agent",
    host="0.0.0.0" if settings.transport == "streamable-http" else "127.0.0.1",
    port=8000,
)
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

    Note: In multi-tenant mode, use the describe_schema and list_tables tools
    instead, as they accept your api_key.
    """
    if not _single_inspector:
        return "Resource unavailable in multi-tenant mode. Use list_tables and describe_schema tools with your api_key."
    return get_schema_overview(_single_inspector)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

# In multi-tenant mode, every tool accepts an optional api_key parameter.
# In single-tenant mode, api_key is simply ignored so existing clients work
# without any configuration change.


@mcp.tool()
def list_tables(api_key: str = "") -> str:
    """List all tables in the database with their row counts.

    Returns a JSON array where each element has ``table_name`` (str) and
    ``row_count`` (int). Call this first to discover what data is available
    before running a query or describing a specific table.

    Args:
        api_key: Your tenant API key (required in multi-tenant mode, ignored otherwise).
    """
    inspector, *_ = _resolve_tenant(api_key or None)
    return _list_tables(inspector)


@mcp.tool()
def describe_schema(table_name: str, api_key: str = "") -> str:
    """Describe the columns, primary keys, foreign keys, and sample values for a table.

    Returns a formatted string with full column metadata — type, nullability,
    whether it is a primary key — plus a few sampled values per column so you
    can see what the data actually looks like before writing a query.

    Call list_tables first if you are unsure which tables exist.

    Args:
        table_name: Name of the table to describe.
        api_key: Your tenant API key (required in multi-tenant mode, ignored otherwise).
    """
    inspector, *_ = _resolve_tenant(api_key or None)
    return _describe_schema(table_name, inspector)


@mcp.tool()
def get_sample_data(table_name: str, limit: int = 5, api_key: str = "") -> str:
    """Get sample rows from a table to understand the data format and values.

    Returns a JSON array of row objects. The limit is clamped to [1, 20];
    use ask_database for larger result sets.

    Call list_tables first if you are unsure which tables exist.

    Args:
        table_name: Name of the table to sample.
        limit: Number of rows to return (1–20). Defaults to 5.
        api_key: Your tenant API key (required in multi-tenant mode, ignored otherwise).
    """
    inspector, *_ = _resolve_tenant(api_key or None)
    return _get_sample_data(table_name, inspector, limit)


@mcp.tool()
async def ask_database(question: str, api_key: str = "") -> str:
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
        api_key: Your tenant API key (required in multi-tenant mode, ignored otherwise).
    """
    resolved_key = api_key or None
    try:
        _, generator, _, _, corrector, dialect = _resolve_tenant(resolved_key)
    except ValueError as exc:
        return json.dumps({"error": str(exc)}, indent=2)

    cache_key = (resolved_key, question.lower().strip())
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
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
