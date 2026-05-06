"""MCP server entrypoint — wires all pipeline components and registers tools/resources."""

import json
import logging
import sys
import time
from typing import cast
from pathlib import Path

# When executed as a script, Python adds `src/` to sys.path but NOT the project root.
# The absolute `src.*` imports below require the project root on sys.path.
_project_root = Path(__file__).parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from mcp.server.fastmcp import FastMCP
from mcp.types import Tool as MCPTool, ToolAnnotations

from src.auth.middleware import user_config_var
from src.config import settings
from src.entitlements.service import EntitlementService
from src.core.logger import get_logger
from src.core.pipeline_factory import PipelineFactory, PipelineComponents
from src.resources.schema_overview import get_schema_overview

from src.tools.describe_schema import describe_schema as _describe_schema
from src.tools.get_sample_data import get_sample_data as _get_sample_data
from src.tools.list_tables import list_tables as _list_tables

# ---------------------------------------------------------------------------
# Module-level references populated by src/app.py lifespan startup.
# ---------------------------------------------------------------------------

_factory: PipelineFactory | None = None
_query_log = None  # QueryLog | None — populated by src/app.py
_user_store = None  # UserStore | None — populated by src/app.py

from cachetools import TTLCache  # type: ignore[import-untyped]

_cache: TTLCache = TTLCache(maxsize=1000, ttl=3600)
CACHE_TTL = 3600

_log = get_logger()
_entitlements = EntitlementService()


def _mcp_oauth_security_schemes() -> list[dict[str, object]]:
    """Return the Apps-compatible auth scheme advertised on OAuth MCP tools."""
    if not settings.mcp_oauth_enabled():
        return []
    return [{"type": "oauth2", "scopes": settings.oauth_required_scopes_list()}]


def _tool_meta(*, invoking: str, invoked: str) -> dict[str, object]:
    """Build ChatGPT Apps metadata while staying harmless for other MCP clients."""
    meta: dict[str, object] = {
        "openai/toolInvocation/invoking": invoking,
        "openai/toolInvocation/invoked": invoked,
    }
    security_schemes = _mcp_oauth_security_schemes()
    if security_schemes:
        meta["securitySchemes"] = security_schemes
    return meta


_READ_ONLY_ANNOTATIONS = ToolAnnotations(readOnlyHint=True)


# ---------------------------------------------------------------------------
# FastMCP factory
# ---------------------------------------------------------------------------


def build_mcp(
    *,
    stateless_http: bool = True,
    json_response: bool = True,
    streamable_http_path: str = "/",
) -> FastMCP:
    return FastMCP(
        "Database Analytics Agent",
        host="0.0.0.0",
        port=settings.port,
        stateless_http=stateless_http,
        json_response=json_response,
        streamable_http_path=streamable_http_path,
    )


# Single shared instance — tools registered here are available in HTTP mode.
mcp = build_mcp(stateless_http=True, json_response=True, streamable_http_path="/")


# ---------------------------------------------------------------------------
# Per-request pipeline resolution
# ---------------------------------------------------------------------------


async def _get_pipeline() -> PipelineComponents:
    global _factory
    user_config = user_config_var.get()

    if _factory is None:
        raise RuntimeError(
            "PipelineFactory not initialised. Start the server with `uvicorn src.app:app`."
        )

    if user_config is None:
        raise RuntimeError("No user config available — missing API key.")

    return await _factory.get(user_config)


def _current_user_id() -> str:
    uc = user_config_var.get()
    if uc is None:
        raise RuntimeError("No user config available — missing API key.")
    return uc.user_id


def _current_api_key_id() -> str | None:
    uc = user_config_var.get()
    return uc.api_key_id if uc is not None else None


def _get_query_log():
    global _query_log
    if _query_log is None:
        raise RuntimeError("QueryLog not initialised. Start the server with `uvicorn src.app:app`.")
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


@mcp.tool(
    title="List database tables",
    annotations=_READ_ONLY_ANNOTATIONS,
    meta=_tool_meta(invoking="Listing tables", invoked="Tables listed"),
)
async def list_tables() -> str:
    """List all tables in the database with their row counts.

    Returns a JSON array where each element has ``table_name`` (str) and
    ``row_count`` (int). Call this first to discover what data is available
    before running a query or describing a specific table.
    """
    pipeline = await _get_pipeline()
    return _list_tables(pipeline.inspector)


@mcp.tool(
    title="Describe database schema",
    annotations=_READ_ONLY_ANNOTATIONS,
    meta=_tool_meta(invoking="Reading schema", invoked="Schema ready"),
)
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


@mcp.tool(
    title="Get sample data",
    annotations=_READ_ONLY_ANNOTATIONS,
    meta=_tool_meta(invoking="Fetching sample rows", invoked="Sample rows ready"),
)
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


@mcp.tool(
    title="Ask database",
    annotations=_READ_ONLY_ANNOTATIONS,
    meta=_tool_meta(invoking="Querying database", invoked="Query complete"),
)
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
        question: Plain-English question about the data.
    """
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

    # --- Cache hit ---
    if cache_key in _cache:
        cached_result, cached_at = _cache[cache_key]
        if now - cached_at < CACHE_TTL:
            payload = json.loads(cached_result)
            payload["cached"] = True
            return json.dumps(payload, indent=2)

    # --- Enforce daily quota BEFORE pipeline resolution ---
    quota_snapshot = None
    entitlement = None
    warning_level = None

    if _user_store is not None:
        quota_snapshot = _user_store.consume_daily_query_quota(user_id)
        entitlement = _entitlements.check_query_quota(
            quota_snapshot.plan_code,
            max(quota_snapshot.daily_count - 1, 0),
        )
        warning_level = _entitlements.quota_warning_level(
            quota_snapshot.plan_code,
            quota_snapshot.daily_count,
        )
        if not entitlement.allowed:
            _log.warning(
                "ask_database",
                extra={
                    "fields": {
                        "tool": "ask_database",
                        "event": "quota_exceeded",
                        "user_id": user_id,
                        "plan_code": entitlement.plan_code,
                        "daily_count": quota_snapshot.daily_count,
                        "quota": entitlement.limit,
                        "warning_level": warning_level,
                        "reset_at": quota_snapshot.daily_quota_reset_at.isoformat(),
                    }
                },
            )
            return json.dumps(
                {
                    "error": "Daily query quota exceeded",
                    "quota": entitlement.limit,
                    "code": entitlement.reason,
                    "plan_code": entitlement.plan_code,
                    "current": quota_snapshot.daily_count,
                    "limit": entitlement.limit,
                    "reset_at": quota_snapshot.daily_quota_reset_at.isoformat(),
                    "warning_level": warning_level,
                    "suggestion": (
                        "Your daily quota resets at midnight UTC. "
                        "Upgrade your plan or try again after the reset."
                    ),
                },
                indent=2,
            )

    # --- Resolve pipeline ---
    pipeline = await _get_pipeline()

    # --- Execute pipeline ---
    start = time.monotonic()
    result = await pipeline.corrector.execute_with_correction(question, pipeline.dialect)
    duration_ms = int((time.monotonic() - start) * 1000)

    sql: str = str(result["sql"])
    attempts: int = cast(int, result["attempts"])
    data: list[dict[str, object]] = cast(list[dict[str, object]], result["data"])
    errors: list[str] = cast(list[str], result["errors"])

    plan_code = quota_snapshot.plan_code if quota_snapshot is not None else None
    daily_count = quota_snapshot.daily_count if quota_snapshot is not None else None
    daily_limit = entitlement.limit if entitlement is not None else None

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
            user_id=user_id,
            api_key_id=api_key_id,
            plan_code=plan_code,
            daily_count=daily_count,
            daily_limit=daily_limit,
            warning_level=warning_level,
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
                    "plan_code": plan_code,
                    "daily_count": daily_count,
                    "daily_limit": daily_limit,
                    "warning_level": warning_level,
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
        user_id=user_id,
        api_key_id=api_key_id,
        plan_code=plan_code,
        daily_count=daily_count,
        daily_limit=daily_limit,
        warning_level=warning_level,
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
                "plan_code": plan_code,
                "daily_count": daily_count,
                "daily_limit": daily_limit,
                "warning_level": warning_level,
            }
        },
    )
    return formatted


@mcp.tool(
    title="View query history",
    annotations=_READ_ONLY_ANNOTATIONS,
    meta=_tool_meta(invoking="Loading query history", invoked="Query history ready"),
)
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
    - ``plan_code``: plan used for quota enforcement on that request
    - ``daily_count`` / ``daily_limit``: quota snapshot at execution time
    - ``warning_level``: quota warning level if usage was elevated

    Args:
        limit: Number of recent queries to return (default 10, max 200).
    """
    user_id = _current_user_id()
    query_log = _get_query_log()
    limit = max(1, min(limit, 200))
    return json.dumps(query_log.get_recent_queries(limit, user_id=user_id), indent=2)


async def _list_tools_with_app_metadata() -> list[MCPTool]:
    """Advertise OAuth security schemes at top level and in _meta for Apps clients."""
    security_schemes = _mcp_oauth_security_schemes()
    tools = await mcp.list_tools()
    if not security_schemes:
        return tools

    enriched: list[MCPTool] = []
    for tool in tools:
        payload = tool.model_dump(by_alias=True, exclude_none=True)
        payload["securitySchemes"] = security_schemes
        meta = dict(payload.get("_meta") or {})
        meta.setdefault("securitySchemes", security_schemes)
        payload["_meta"] = meta
        enriched.append(MCPTool.model_validate(payload))
    return enriched


mcp._mcp_server.list_tools()(_list_tools_with_app_metadata)  # type: ignore[attr-defined]
