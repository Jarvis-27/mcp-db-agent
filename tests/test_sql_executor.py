"""Tests for SQLExecutor — runs validated SQL against demo.db."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine

from src.config import settings
from src.core.sql_executor import SQLExecutor


@pytest.fixture(scope="module")
def engine():
    return create_engine(settings.database_url)


@pytest.fixture(scope="module")
def executor(engine):
    pool = ThreadPoolExecutor(max_workers=2)
    return SQLExecutor(engine, settings, pool)


# ---------------------------------------------------------------------------
# Return type checks
# ---------------------------------------------------------------------------


async def test_execute_returns_list(executor):
    rows = await executor.execute("SELECT * FROM users LIMIT 5")
    assert isinstance(rows, list)


async def test_execute_rows_are_dicts(executor):
    rows = await executor.execute("SELECT * FROM users LIMIT 3")
    assert all(isinstance(r, dict) for r in rows)


# ---------------------------------------------------------------------------
# Row count and column checks
# ---------------------------------------------------------------------------


async def test_execute_respects_limit(executor):
    rows = await executor.execute("SELECT * FROM products LIMIT 10")
    assert len(rows) == 10


async def test_execute_returns_requested_columns(executor):
    rows = await executor.execute("SELECT id, name, email FROM users LIMIT 1")
    assert len(rows) == 1
    assert set(rows[0].keys()) == {"id", "name", "email"}


async def test_execute_empty_result(executor):
    rows = await executor.execute("SELECT * FROM users WHERE email = 'nobody@nowhere.invalid'")
    assert rows == []


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------


async def test_execute_aggregation_count(executor):
    rows = await executor.execute("SELECT COUNT(*) AS total FROM users")
    assert len(rows) == 1
    assert rows[0]["total"] == 500


async def test_execute_aggregation_group_by(executor):
    rows = await executor.execute("SELECT status, COUNT(*) AS cnt FROM orders GROUP BY status")
    assert len(rows) > 0
    statuses = {r["status"] for r in rows}
    assert statuses.issubset({"pending", "shipped", "delivered", "cancelled"})


# ---------------------------------------------------------------------------
# JOIN query
# ---------------------------------------------------------------------------


async def test_execute_join_query(executor):
    sql = "SELECT o.id, u.name FROM orders o JOIN users u ON o.user_id = u.id LIMIT 5"
    rows = await executor.execute(sql)
    assert len(rows) == 5
    assert "id" in rows[0]
    assert "name" in rows[0]


# ---------------------------------------------------------------------------
# Error propagation — executor must NOT swallow exceptions
# ---------------------------------------------------------------------------


async def test_execute_raises_on_unknown_table(executor):
    with pytest.raises(Exception):
        await executor.execute("SELECT * FROM nonexistent_table_xyz")


async def test_execute_raises_on_bad_syntax(executor):
    with pytest.raises(Exception):
        await executor.execute("THIS IS NOT SQL AT ALL !!!")
