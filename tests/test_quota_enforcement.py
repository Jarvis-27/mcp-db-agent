"""Tests for ask_database quota enforcement in src/server.py."""

import json
import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pipeline():
    corrector = MagicMock()
    corrector.execute_with_correction = AsyncMock(
        return_value={
            "success": True,
            "sql": "SELECT 1",
            "data": [{"n": 1}],
            "attempts": 1,
            "errors": [],
        }
    )
    formatter = MagicMock()
    formatter.format.return_value = json.dumps(
        {
            "query": "SELECT 1",
            "row_count": 1,
            "columns": ["n"],
            "data": [{"n": 1}],
            "attempts": 1,
        }
    )
    pipeline = MagicMock()
    pipeline.corrector = corrector
    pipeline.dialect = "sqlite"
    pipeline.formatter = formatter
    return pipeline


def _make_user_store(*, daily_count: int, plan_code: str = "free"):
    """Return a mock UserStore whose consume_daily_query_quota returns a snapshot."""
    us = MagicMock()
    us.consume_daily_query_quota.return_value = SimpleNamespace(
        tenant_id="test-user-id",
        plan_code=plan_code,
        daily_count=daily_count,
        daily_quota_reset_at=datetime.now(UTC) + timedelta(hours=1),
    )
    return us


def _empty_cache():
    """Return a plain dict standing in for an empty TTLCache."""
    return {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_ask_database_within_quota_succeeds():
    """Requests within quota should execute normally and increment the counter."""
    import src.server as server

    pipeline = _make_pipeline()
    user_store = _make_user_store(daily_count=1, plan_code="free")
    query_log = MagicMock()

    with (
        patch.object(server, "_user_store", user_store),
        patch.object(server, "_get_pipeline", AsyncMock(return_value=pipeline)),
        patch("src.server._current_user_id", return_value="test-user-id"),
        patch.object(server, "_get_query_log", return_value=query_log),
        patch.object(server, "_cache", _empty_cache()),
    ):
        result = json.loads(await server.ask_database("How many users?"))

    assert "error" not in result
    user_store.consume_daily_query_quota.assert_called_once_with("test-user-id")


async def test_ask_database_quota_exceeded_returns_error():
    """Requests beyond quota must return a quota error without running the pipeline."""
    import src.server as server

    pipeline = _make_pipeline()
    user_store = _make_user_store(daily_count=26, plan_code="free")
    get_pipeline_mock = AsyncMock(return_value=pipeline)

    with (
        patch.object(server, "_user_store", user_store),
        patch.object(server, "_get_pipeline", get_pipeline_mock),
        patch("src.server._current_user_id", return_value="test-user-id"),
        patch.object(server, "_get_query_log", return_value=MagicMock()),
        patch.object(server, "_cache", _empty_cache()),
    ):
        result = json.loads(await server.ask_database("How many users?"))

    assert result["error"] == "Daily query quota exceeded"
    assert result["quota"] == 25
    assert result["code"] == "daily_quota_exceeded"
    assert result["plan_code"] == "free"
    assert result["current"] == 26
    assert result["limit"] == 25
    assert "reset_at" in result
    assert "suggestion" in result
    # Pipeline must NOT have run
    pipeline.corrector.execute_with_correction.assert_not_awaited()
    # _get_pipeline must NEVER be called — quota check must happen before
    # pipeline resolution so cold-path DB work is never triggered for
    # over-quota requests.
    get_pipeline_mock.assert_not_awaited()


async def test_ask_database_at_quota_boundary_succeeds():
    """The request that brings count exactly to the limit should still succeed."""
    import src.server as server

    pipeline = _make_pipeline()
    user_store = _make_user_store(daily_count=25, plan_code="free")
    query_log = MagicMock()

    with (
        patch.object(server, "_user_store", user_store),
        patch.object(server, "_get_pipeline", AsyncMock(return_value=pipeline)),
        patch("src.server._current_user_id", return_value="test-user-id"),
        patch.object(server, "_get_query_log", return_value=query_log),
        patch.object(server, "_cache", _empty_cache()),
    ):
        result = json.loads(await server.ask_database("How many users?"))

    assert "error" not in result
    pipeline.corrector.execute_with_correction.assert_awaited_once()


async def test_ask_database_pro_plan_uses_higher_limit():
    """Pro tenants should receive the higher plan quota."""
    import src.server as server

    pipeline = _make_pipeline()
    user_store = _make_user_store(daily_count=500, plan_code="pro")
    query_log = MagicMock()

    with (
        patch.object(server, "_user_store", user_store),
        patch.object(server, "_get_pipeline", AsyncMock(return_value=pipeline)),
        patch("src.server._current_user_id", return_value="test-user-id"),
        patch.object(server, "_get_query_log", return_value=query_log),
        patch.object(server, "_cache", _empty_cache()),
    ):
        result = json.loads(await server.ask_database("How many users?"))

    assert "error" not in result
    user_store.consume_daily_query_quota.assert_called_once_with("test-user-id")


async def test_ask_database_stdio_bypasses_quota():
    """stdio users (user_id == '__stdio__') are never subject to quota."""
    import src.server as server

    pipeline = _make_pipeline()
    user_store = _make_user_store(daily_count=9999, plan_code="free")
    query_log = MagicMock()

    with (
        patch.object(server, "_user_store", user_store),
        patch.object(server, "_get_pipeline", AsyncMock(return_value=pipeline)),
        patch("src.server._current_user_id", return_value="__stdio__"),
        patch.object(server, "_get_query_log", return_value=query_log),
        patch.object(server, "_cache", _empty_cache()),
    ):
        result = json.loads(await server.ask_database("How many users?"))

    # No quota error for stdio
    assert "Daily query quota exceeded" not in result.get("error", "")
    # UserStore must never be touched for stdio
    user_store.consume_daily_query_quota.assert_not_called()


async def test_ask_database_no_user_store_bypasses_quota():
    """When _user_store is None (stdio mode before app.py wires it up), quota is skipped."""
    import src.server as server

    pipeline = _make_pipeline()
    query_log = MagicMock()

    with (
        patch.object(server, "_user_store", None),
        patch.object(server, "_get_pipeline", AsyncMock(return_value=pipeline)),
        patch("src.server._current_user_id", return_value="some-user-id"),
        patch.object(server, "_get_query_log", return_value=query_log),
        patch.object(server, "_cache", _empty_cache()),
    ):
        result = json.loads(await server.ask_database("How many users?"))

    assert "error" not in result


async def test_ask_database_cache_hit_bypasses_quota():
    """Cache hits must not count against quota (no LLM/DB work occurs)."""
    import src.server as server

    user_store = _make_user_store(daily_count=999, plan_code="free")
    question = "How many users?"
    user_id = "test-user-id"
    cache_key = (user_id, question.lower().strip())
    cached_payload = json.dumps(
        {"query": "SELECT count(*) FROM users", "row_count": 500, "data": []}
    )

    pre_populated_cache = {cache_key: (cached_payload, time.monotonic())}

    with (
        patch.object(server, "_user_store", user_store),
        patch("src.server._current_user_id", return_value=user_id),
        patch.object(server, "_cache", pre_populated_cache),
        patch.object(server, "_get_pipeline", AsyncMock()),  # should not be called
    ):
        result = json.loads(await server.ask_database(question))

    assert result.get("cached") is True
    user_store.consume_daily_query_quota.assert_not_called()
