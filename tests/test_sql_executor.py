"""Tests for SQLExecutor — runs validated SQL against a self-contained in-memory DB.

The fixture creates the minimal demo schema (users, products, orders) and seeds
enough data for every assertion in this file, so the tests are independent of
any operator .env or external DATABASE_URL.
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

from src.core.sql_executor import SQLExecutor


# ---------------------------------------------------------------------------
# Minimal demo schema
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _User(_Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    email = Column(String, nullable=False)


class _Product(_Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class _Order(_Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    status = Column(String, nullable=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STATUSES = ["pending", "shipped", "delivered", "cancelled"]


@pytest.fixture(scope="module")
def engine():
    """Shared in-memory SQLite engine seeded with demo-like data.

    StaticPool ensures every SQLAlchemy connection (including those opened by
    the thread-pool executor) sees the same in-memory database.
    """
    e = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _Base.metadata.create_all(e)
    with Session(e) as session:
        # 500 users — test_execute_aggregation_count asserts exactly 500
        session.add_all(
            [_User(id=i, name=f"User {i}", email=f"user{i}@example.com") for i in range(1, 501)]
        )
        session.flush()
        # 14 products — test_execute_respects_limit uses LIMIT 10, so we need ≥10
        session.add_all([_Product(id=i, name=f"Product {i}") for i in range(1, 15)])
        # 20 orders covering all four statuses evenly
        session.add_all(
            [
                _Order(
                    id=i,
                    user_id=((i - 1) % 500) + 1,
                    status=_STATUSES[(i - 1) % 4],
                )
                for i in range(1, 21)
            ]
        )
        session.commit()
    return e


def _make_settings(timeout: int = 30) -> MagicMock:
    s = MagicMock()
    s.query_timeout_seconds = timeout
    return s


@pytest.fixture(scope="module")
def executor(engine):
    pool = ThreadPoolExecutor(max_workers=2)
    return SQLExecutor(engine, _make_settings(), pool)


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
