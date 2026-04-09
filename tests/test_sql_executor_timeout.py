"""Unit tests for SQLExecutor timeout behaviour — no real DB required.

Covers:
- PostgreSQL connect_args include statement_timeout in options.
- SQLite timer fires interrupt() on slow queries.
- Fast queries cancel the timer before it fires.
- asyncio.TimeoutError is raised when thread blocks past deadline.
- Timer is always cancelled via finally (no dangling timers on success or error).
- No Python timer is created for PostgreSQL (server-side only).
"""

import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.engine.url import make_url

from src.core.pipeline_factory import PipelineFactory
from src.core.sql_executor import SQLExecutor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(timeout: int = 30) -> MagicMock:
    s = MagicMock()
    s.query_timeout_seconds = timeout
    return s


def _make_mock_engine(dialect: str) -> MagicMock:
    engine = MagicMock()
    engine.dialect.name = dialect
    return engine


def _make_executor(dialect: str = "sqlite", timeout: int = 30) -> tuple[SQLExecutor, MagicMock]:
    """Return (executor, mock_engine) for the given dialect."""
    engine = _make_mock_engine(dialect)
    pool = ThreadPoolExecutor(max_workers=2)
    executor = SQLExecutor(engine, _make_settings(timeout), pool)
    return executor, engine


def _make_factory() -> PipelineFactory:
    pool = ThreadPoolExecutor(max_workers=1)
    settings = MagicMock()
    settings.query_timeout_seconds = 30
    settings.schema_cache_ttl_seconds = 600
    settings.allow_sqlite_user_dbs = False
    settings.environment = "development"
    return PipelineFactory(settings, pool)


def _setup_mock_conn(mock_engine: MagicMock, result_rows=None, execute_side_effect=None):
    """Wire up mock_engine.connect() context manager with a mock SA connection."""
    mock_raw_conn = MagicMock()
    mock_sa_conn = MagicMock()
    mock_sa_conn.connection.driver_connection = mock_raw_conn

    if execute_side_effect is not None:
        mock_sa_conn.execute.side_effect = execute_side_effect
    else:
        rows = result_rows if result_rows is not None else []
        mock_result = MagicMock()
        mock_result.mappings.return_value.all.return_value = rows
        mock_sa_conn.execute.return_value = mock_result

    mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_sa_conn)
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)
    return mock_raw_conn, mock_sa_conn


# ---------------------------------------------------------------------------
# 1-4: PostgreSQL connect_args from _connect_args_for
# ---------------------------------------------------------------------------


def test_connect_args_postgresql_no_startup_options():
    """connect_args must NOT include startup options — poolers like Neon reject them."""
    factory = _make_factory()
    pg_url = make_url("postgresql+psycopg2://user:pass@localhost/mydb")
    args = factory._connect_args_for(pg_url, 30)

    assert "options" not in args


def test_postgresql_run_query_sets_statement_timeout():
    """_run_query must SET LOCAL statement_timeout per connection for PostgreSQL."""
    executor, engine = _make_executor(dialect="postgresql", timeout=30)

    mock_conn_final = MagicMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_conn_final.execute.return_value = mock_result

    mock_sa_conn = MagicMock()
    mock_sa_conn.execution_options.return_value = mock_conn_final
    engine.connect.return_value.__enter__ = MagicMock(return_value=mock_sa_conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    executor._run_query("SELECT 1")

    executed_sql = [str(call.args[0]) for call in mock_conn_final.execute.call_args_list]
    assert any("statement_timeout" in s for s in executed_sql)
    assert any("30000" in s for s in executed_sql)


def test_postgresql_run_query_statement_timeout_scales():
    """_run_query must scale timeout_seconds to milliseconds for PostgreSQL."""
    executor, engine = _make_executor(dialect="postgresql", timeout=15)

    mock_conn_final = MagicMock()
    mock_result = MagicMock()
    mock_result.mappings.return_value.all.return_value = []
    mock_conn_final.execute.return_value = mock_result

    mock_sa_conn = MagicMock()
    mock_sa_conn.execution_options.return_value = mock_conn_final
    engine.connect.return_value.__enter__ = MagicMock(return_value=mock_sa_conn)
    engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    executor._run_query("SELECT 1")

    executed_sql = [str(call.args[0]) for call in mock_conn_final.execute.call_args_list]
    assert any("15000" in s for s in executed_sql)


def test_connect_args_postgresql_retains_connect_timeout():
    factory = _make_factory()
    pg_url = make_url("postgresql://user:pass@localhost/mydb")
    args = factory._connect_args_for(pg_url, 30)

    assert args.get("connect_timeout") == 10


def test_connect_args_sqlite_has_no_options():
    factory = _make_factory()
    sqlite_url = make_url("sqlite:///./test.db")
    args = factory._connect_args_for(sqlite_url, 30)

    assert "options" not in args
    assert "statement_timeout" not in str(args)


# ---------------------------------------------------------------------------
# 5: SQLite timer fires interrupt() on slow query
# ---------------------------------------------------------------------------


def test_sqlite_timer_fires_interrupt_on_slow_query():
    executor, engine = _make_executor(dialect="sqlite", timeout=30)
    executor._timeout = 0.1  # 100ms for fast test

    def _slow_execute(_sql):
        time.sleep(0.4)  # longer than timeout
        raise Exception("interrupted")

    mock_raw_conn, _ = _setup_mock_conn(engine, execute_side_effect=_slow_execute)

    with pytest.raises(Exception):
        executor._run_query("SELECT 1")

    assert mock_raw_conn.interrupt.call_count == 1


# ---------------------------------------------------------------------------
# 6: Fast query cancels timer before it fires
# ---------------------------------------------------------------------------


def test_sqlite_timer_cancelled_on_fast_query():
    executor, engine = _make_executor(dialect="sqlite", timeout=30)
    mock_raw_conn, _ = _setup_mock_conn(engine, result_rows=[{"id": 1}])

    result = executor._run_query("SELECT 1")

    assert result == [{"id": 1}]
    mock_raw_conn.interrupt.assert_not_called()


# ---------------------------------------------------------------------------
# 7: Timer cancelled via finally on success
# ---------------------------------------------------------------------------


def test_timer_cancelled_on_success():
    executor, engine = _make_executor(dialect="sqlite", timeout=30)
    _setup_mock_conn(engine, result_rows=[{"n": 42}])

    cancelled: list[threading.Timer] = []
    original_cancel = threading.Timer.cancel

    def _tracking_cancel(t):
        cancelled.append(t)
        original_cancel(t)

    with patch.object(threading.Timer, "cancel", _tracking_cancel):
        executor._run_query("SELECT 1")

    assert len(cancelled) == 1


# ---------------------------------------------------------------------------
# 8: Timer cancelled via finally on execution error
# ---------------------------------------------------------------------------


def test_timer_cancelled_on_execution_error():
    executor, engine = _make_executor(dialect="sqlite", timeout=30)
    _setup_mock_conn(engine, execute_side_effect=RuntimeError("DB error"))

    cancelled: list[threading.Timer] = []
    original_cancel = threading.Timer.cancel

    def _tracking_cancel(t):
        cancelled.append(t)
        original_cancel(t)

    with patch.object(threading.Timer, "cancel", _tracking_cancel):
        with pytest.raises(RuntimeError, match="DB error"):
            executor._run_query("SELECT 1")

    assert len(cancelled) == 1


# ---------------------------------------------------------------------------
# 9: No Python timer started for PostgreSQL (server-side only)
# ---------------------------------------------------------------------------


def test_no_timer_for_postgresql():
    executor, engine = _make_executor(dialect="postgresql", timeout=30)
    _setup_mock_conn(engine, result_rows=[])

    started: list[threading.Timer] = []
    original_start = threading.Timer.start

    def _tracking_start(t):
        started.append(t)
        original_start(t)

    with patch.object(threading.Timer, "start", _tracking_start):
        executor._run_query("SELECT 1")

    assert len(started) == 0


# ---------------------------------------------------------------------------
# 10: asyncio.TimeoutError raised when thread blocks past deadline
# ---------------------------------------------------------------------------


async def test_execute_raises_timeout_error_when_query_hangs():
    executor, engine = _make_executor(dialect="sqlite", timeout=30)
    executor._timeout = 0.05  # 50ms

    def _blocking(_sql):
        time.sleep(10)

    _setup_mock_conn(engine, execute_side_effect=_blocking)

    with pytest.raises(asyncio.TimeoutError):
        await executor.execute("SELECT 1")
