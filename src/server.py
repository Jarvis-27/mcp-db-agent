"""MCP server entrypoint — wires all pipeline components and registers tools/resources."""

import json
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import cast
from pathlib import Path

# When executed as a script (`uv run src/server.py`), Python adds `src/` to
# sys.path but NOT the project root.  The absolute `src.*` imports below
# require the project root on sys.path, so we insert it before they resolve.
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from mcp.server.fastmcp import FastMCP

from src.auth.middleware import user_config_var
from src.config import settings
from src.core.logger import get_logger
from src.core.pipeline_factory import PipelineFactory, PipelineComponents
from src.resources.schema_overview import get_schema_overview

# Import tool implementations under private aliases so the public names below
# can be used as the MCP-visible tool names without shadowing the imports.
from src.tools.describe_schema import describe_schema as _describe_schema
from src.tools.get_sample_data import get_sample_data as _get_sample_data
from src.tools.list_tables import list_tables as _list_tables

# ---------------------------------------------------------------------------
# Module-level references populated by src/app.py lifespan startup.
# In stdio mode they are created lazily inside _get_pipeline().
# ---------------------------------------------------------------------------

_factory: PipelineFactory | None = None
_query_log = None  # QueryLog | None — populated by src/app.py
_user_store = None  # UserStore | None — populated by src/app.py

# Bounded TTL cache — multi-tenant safe (keyed on (user_id, question)).
# In HTTP mode this is populated from src/app.py. In stdio mode it is
# a module-level dict for backward compat.
from cachetools import TTLCache  # type: ignore[import-untyped]

_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)
CACHE_TTL = 3600

_log = get_logger()


# ---------------------------------------------------------------------------
# FastMCP factory
# ---------------------------------------------------------------------------


def build_mcp(
    *,
    stateless_http: bool = True,
    json_response: bool = True,
    streamable_http_path: str = "/",
) -> FastMCP:
    """Construct the FastMCP instance with the requested HTTP flags.

    Called by src/app.py for hosted mode and by __main__ for stdio mode.
    """
    return FastMCP(
        "Database Analytics Agent",
        host="0.0.0.0",
        port=settings.port,
        stateless_http=stateless_http,
        json_response=json_response,
        streamable_http_path=streamable_http_path,
    )


# Single shared instance — tools registered here are available in both stdio and HTTP mode.
# stateless_http/json_response are ignored by the stdio transport.
mcp = build_mcp(stateless_http=True, json_response=True, streamable_http_path="/")


# ---------------------------------------------------------------------------
# Per-request pipeline resolution
# ---------------------------------------------------------------------------


async def _get_pipeline() -> PipelineComponents:
    global _factory
    user_config = user_config_var.get()

    if _factory is None:
        # Stdio fallback: build a factory the first time.
        _factory = PipelineFactory(settings, ThreadPoolExecutor(max_workers=8))

    if user_config is not None:
        return await _factory.get(user_config)

    return _factory.get_from_settings(settings)


def _current_user_id() -> str:
    uc = user_config_var.get()
    return uc.user_id if uc is not None else "__stdio__"


def _current_api_key_id() -> str | None:
    uc = user_config_var.get()
    return uc.api_key_id if uc is not None else None


def _get_query_log():
    """Return the query log instance.

    When AUTH_DATABASE_URL is set to a PostgreSQL database (e.g. Neon), query
    history is written there — the query_history table is created by the initial
    Alembic migration.  Without AUTH_DATABASE_URL, falls back to a local
    SQLite file (query_log.db) for simple stdio-only setups.
    """
    global _query_log
    if _query_log is None:
        from sqlalchemy import create_engine
        from src.core.query_log import QueryLog

        auth_url = settings.auth_database_url
        if not auth_url.startswith("sqlite"):
            # PostgreSQL (or other network DB) configured — use it directly.
            # Create only the query_history table if it doesn't exist yet;
            # we never touch other tables in the database.
            from src.auth.user_store import QueryHistory

            connect_args = {"connect_timeout": 10} if auth_url.startswith("postgresql") else {}
            log_engine = create_engine(auth_url, connect_args=connect_args)
            QueryHistory.__table__.create(log_engine, checkfirst=True)
        else:
            # No explicit auth DB — fall back to a local SQLite query_log.db.
            from pathlib import Path
            from sqlalchemy import inspect as _inspect, text
            from src.auth.user_store import Base

            db_path = str(Path(__file__).parent.parent / "query_log.db")
            log_engine = create_engine(f"sqlite:///{db_path}")
            Base.metadata.create_all(log_engine)
            # Schema guard: ensure tenant_id exists if the file predates the
            # tenant-scoped query history model.
            with log_engine.connect() as conn:
                insp = _inspect(log_engine)
                if "query_history" in insp.get_table_names():
                    col_names = {c["name"] for c in insp.get_columns("query_history")}
                    if "tenant_id" not in col_names:
                        conn.execute(
                            text(
                                "ALTER TABLE query_history "
                                "ADD COLUMN tenant_id TEXT NOT NULL DEFAULT '__stdio__'"
                            )
                        )
                        conn.commit()
                    if "api_key_id" not in col_names:
                        conn.execute(
                            text("ALTER TABLE query_history ADD COLUMN api_key_id TEXT NULL")
                        )
                        conn.commit()

        _query_log = QueryLog(log_engine)
    return _query_log


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


@mcp.resource("schema://overview")
async def schema_overview() -> str:
    """Full database schema in compact DDL-like notation.

    Fetch this resource to inject the complete table and column definitions
    into your context before writing a query. It covers every table, column
    type, primary key, and foreign key relationship — equivalent to calling
    describe_schema on every table at once but faster.
    """
    pipeline = await _get_pipeline()
    return get_schema_overview(pipeline.inspector)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_tables() -> str:
    """List all tables in the database with their row counts.

    Returns a JSON array where each element has ``table_name`` (str) and
    ``row_count`` (int). Call this first to discover what data is available
    before running a query or describing a specific table.
    """
    pipeline = await _get_pipeline()
    return _list_tables(pipeline.inspector)


@mcp.tool()
async def describe_schema(table_name: str) -> str:
    """Describe the columns, primary keys, foreign keys, and sample values for a table.

    Returns a formatted string with full column metadata — type, nullability,
    whether it is a primary key — plus a few sampled values per column so you
    can see what the data actually looks like before writing a query.

    Call list_tables first if you are unsure which tables exist.

    Args:
        table_name: Name of the table to describe.
    """
    pipeline = await _get_pipeline()
    return _describe_schema(table_name, pipeline.inspector)


@mcp.tool()
async def get_sample_data(table_name: str, limit: int = 5) -> str:
    """Get sample rows from a table to understand the data format and values.

    Returns a JSON array of row objects. The limit is clamped to [1, 20];
    use ask_database for larger result sets.

    Call list_tables first if you are unsure which tables exist.

    Args:
        table_name: Name of the table to sample.
        limit: Number of rows to return (1–20). Defaults to 5.
    """
    pipeline = await _get_pipeline()
    return _get_sample_data(table_name, pipeline.inspector, limit)


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
    # Resolve user identity and cache key before any I/O so we can short-circuit
    # cheaply for cache hits and enforce quota BEFORE cold-path DB work.
    user_id = _current_user_id()
    api_key_id = _current_api_key_id()
    query_log = _get_query_log()

    cache_key = (user_id, question.lower().strip())
    now = time.monotonic()

    _log.info(
        "ask_database",
        extra={
            "fields": {
                "tool": "ask_database",
                "event": "started",
                "question": question,
                "user_id": user_id,
            }
        },
    )

    # --- Cache hit (no quota increment; no DB or LLM work) ---
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
                        "user_id": user_id,
                        "cached": True,
                    }
                },
            )
            return json.dumps(payload, indent=2)

    # --- Enforce daily quota BEFORE pipeline resolution (hosted mode only) ---
    # Quota must be checked here so that over-quota requests never trigger a
    # cold-path DB connection inside _get_pipeline() / _build_components().
    if user_id != "__stdio__" and _user_store is not None:
        new_count = _user_store.increment_daily_quota(user_id)
        if new_count > settings.ask_database_quota_per_day:
            _log.warning(
                "ask_database",
                extra={
                    "fields": {
                        "tool": "ask_database",
                        "event": "quota_exceeded",
                        "user_id": user_id,
                        "daily_count": new_count,
                        "quota": settings.ask_database_quota_per_day,
                    }
                },
            )
            return json.dumps(
                {
                    "error": "Daily query quota exceeded",
                    "quota": settings.ask_database_quota_per_day,
                    "suggestion": (
                        "Your daily quota resets at midnight UTC. "
                        "Contact your administrator to increase your limit."
                    ),
                },
                indent=2,
            )

    # --- Resolve pipeline (cold-path DB connect happens here if not cached) ---
    pipeline = await _get_pipeline()

    # --- Execute pipeline ---
    start = time.monotonic()
    result = await pipeline.corrector.execute_with_correction(question, pipeline.dialect)
    duration_ms = int((time.monotonic() - start) * 1000)

    sql: str = str(result["sql"])
    attempts: int = cast(int, result["attempts"])
    data: list[dict[str, object]] = cast(list[dict[str, object]], result["data"])
    errors: list[str] = cast(list[str], result["errors"])

    if result["success"]:
        formatted = pipeline.formatter.format(sql, data, attempts)
        query_log.log_query(
            question=question,
            sql=sql,
            success=True,
            row_count=len(data),
            attempts=attempts,
            duration_ms=duration_ms,
            error=None,
            tenant_id=user_id,
            api_key_id=api_key_id,
        )
        _cache[cache_key] = (formatted, time.monotonic())
        log_level = logging.WARNING if attempts > 1 else logging.INFO
        _log.log(
            log_level,
            "ask_database",
            extra={
                "fields": {
                    "tool": "ask_database",
                    "event": "completed",
                    "question": question,
                    "user_id": user_id,
                    "generated_sql": sql,
                    "execution_time_ms": duration_ms,
                    "result_row_count": len(data),
                    "attempts": attempts,
                    "error": None,
                }
            },
        )
        return formatted

    last_error = errors[-1] if errors else "Query failed after maximum retries"
    formatted = pipeline.formatter.format_error(last_error, sql, errors)
    query_log.log_query(
        question=question,
        sql=sql,
        success=False,
        row_count=0,
        attempts=attempts,
        duration_ms=duration_ms,
        error=last_error,
        tenant_id=user_id,
        api_key_id=api_key_id,
    )
    _log.error(
        "ask_database",
        extra={
            "fields": {
                "tool": "ask_database",
                "event": "completed",
                "question": question,
                "user_id": user_id,
                "generated_sql": result["sql"],
                "execution_time_ms": duration_ms,
                "result_row_count": 0,
                "attempts": result["attempts"],
                "error": last_error,
            }
        },
    )
    return formatted


@mcp.tool()
async def query_history(limit: int = 10) -> str:
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
        limit: Number of recent queries to return (default 10, max 200).
    """
    user_id = _current_user_id()
    query_log = _get_query_log()
    limit = max(1, min(limit, 200))
    return json.dumps(query_log.get_recent_queries(limit, tenant_id=user_id), indent=2)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if settings.transport == "streamable-http":
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
