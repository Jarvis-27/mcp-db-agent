"""Tests for query_history tool — limit clamping."""

import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import src.server as server
from src.auth.user_store import Base
from src.core.query_log import QueryLog


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
    mock_log.get_recent_queries.assert_called_once_with(10, user_id="user-1")


async def test_query_history_large_limit_clamped_to_200():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history(limit=999_999)
    mock_log.get_recent_queries.assert_called_once_with(200, user_id="user-1")


async def test_query_history_zero_clamped_to_1():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history(limit=0)
    mock_log.get_recent_queries.assert_called_once_with(1, user_id="user-1")


async def test_query_history_negative_clamped_to_1():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history(limit=-50)
    mock_log.get_recent_queries.assert_called_once_with(1, user_id="user-1")


async def test_query_history_at_max_passes_through():
    mock_log = _make_mock_log()
    with (
        patch("src.server._current_user_id", return_value="user-1"),
        patch("src.server._get_query_log", return_value=mock_log),
    ):
        await server.query_history(limit=200)
    mock_log.get_recent_queries.assert_called_once_with(200, user_id="user-1")


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
            "user_id": "user-1",
            "plan_code": "free",
            "daily_count": 7,
            "daily_limit": 25,
            "warning_level": None,
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
    assert parsed[0]["plan_code"] == "free"
    assert parsed[0]["daily_limit"] == 25


def test_query_log_persists_plan_and_quota_context():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    log = QueryLog(engine)

    try:
        log.log_query(
            question="Which customers churned?",
            sql="SELECT * FROM customers",
            success=True,
            row_count=3,
            attempts=1,
            duration_ms=12,
            error=None,
            user_id="user-1",
            api_key_id="key-1",
            plan_code="pro",
            daily_count=321,
            daily_limit=500,
            warning_level="medium",
        )
        rows = log.get_recent_queries(user_id="user-1")
    finally:
        engine.dispose()

    assert len(rows) == 1
    assert rows[0]["plan_code"] == "pro"
    assert rows[0]["daily_count"] == 321
    assert rows[0]["daily_limit"] == 500
    assert rows[0]["warning_level"] == "medium"


def _seed_durations(log, durations):
    for i, ms in enumerate(durations):
        log.log_query(
            question="q",
            sql="SELECT 1",
            success=True,
            row_count=1,
            attempts=1,
            duration_ms=ms,
            error=None,
            user_id=f"user-{i}",
            api_key_id=None,
        )


def test_aggregate_stats_percentiles_over_full_dataset():
    """p50/p95 are computed correctly over all of today's rows (below the cap)."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    log = QueryLog(engine)
    try:
        _seed_durations(log, [10, 20, 30, 40, 50, 60, 70, 80, 90, 100])
        stats = log.get_aggregate_stats_today()
    finally:
        engine.dispose()

    assert stats.total == 10
    assert stats.p50_duration_ms == 50
    assert stats.p95_duration_ms == 100


def test_aggregate_stats_percentiles_not_biased_to_fastest_when_capped(monkeypatch):
    """Regression: once a day exceeds the sample cap, percentiles must reflect a
    slice of the whole distribution — not the N *fastest* rows (which an
    `ORDER BY duration_ms ASC LIMIT N` would select, pinning p95 artificially low).
    """
    import src.core.query_log as query_log_module

    monkeypatch.setattr(query_log_module, "_MAX_PERCENTILE_SAMPLES", 5)

    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    log = QueryLog(engine)
    try:
        # Insert the slow rows first, then the fast rows. The biased query would
        # keep only the five 1 ms rows and report p95 == 1.
        _seed_durations(log, [1000, 1000, 1000, 1000, 1000, 1, 1, 1, 1, 1])
        stats = log.get_aggregate_stats_today()
    finally:
        engine.dispose()

    assert stats.total == 10
    # The sample is no longer the five fastest, so p95 is not pinned to 1 ms.
    assert stats.p95_duration_ms is not None
    assert stats.p95_duration_ms >= 500
