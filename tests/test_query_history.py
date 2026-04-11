"""Tests for query_history tool — limit clamping."""

import json
from unittest.mock import MagicMock, patch

import pytest

import src.server as server


@pytest.fixture(autouse=True)
def _reset_server_state():
    """Ensure module-level singletons don't bleed between tests."""
    original_query_log = server._query_log
    yield
    server._query_log = original_query_log


def _make_mock_log(rows=None):
    mock_log = MagicMock()
    mock_log.get_recent_queries.return_value = rows or []
    return mock_log


async def test_query_history_default_limit():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history()
    mock_log.get_recent_queries.assert_called_once_with(10, tenant_id="user-1")


async def test_query_history_large_limit_clamped_to_200():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history(limit=999_999)
    mock_log.get_recent_queries.assert_called_once_with(200, tenant_id="user-1")


async def test_query_history_zero_clamped_to_1():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history(limit=0)
    mock_log.get_recent_queries.assert_called_once_with(1, tenant_id="user-1")


async def test_query_history_negative_clamped_to_1():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history(limit=-50)
    mock_log.get_recent_queries.assert_called_once_with(1, tenant_id="user-1")


async def test_query_history_at_max_passes_through():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history(limit=200)
    mock_log.get_recent_queries.assert_called_once_with(200, tenant_id="user-1")


async def test_query_history_returns_json():
    rows = [
        {
            "id": 1,
            "question": "test",
            "sql": "SELECT 1",
            "success": True,
            "row_count": 1,
            "attempts": 1,
            "duration_ms": 5,
            "error": None,
            "timestamp": "2026-01-01T00:00:00+00:00",
            "tenant_id": "user-1",
        }
    ]
    mock_log = _make_mock_log(rows=rows)
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        result = await server.query_history(limit=5)
    parsed = json.loads(result)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["question"] == "test"
