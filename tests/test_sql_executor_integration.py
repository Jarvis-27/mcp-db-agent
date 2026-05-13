"""Integration tests for server-side query cancellation (G8).

These exercise the real DB driver — they prove that ``QUERY_TIMEOUT_SECONDS``
results in the *server* killing the query, not just the client coroutine
returning early.  The Postgres test is gated on a real DATABASE_URL because
nothing else in this test exercises Postgres locally.
"""

import os
import sqlite3
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from src.core.sql_executor import SQLExecutor


def _make_executor(engine, timeout_seconds: float = 1.0) -> SQLExecutor:
    settings = MagicMock()
    settings.query_timeout_seconds = timeout_seconds
    pool = ThreadPoolExecutor(max_workers=2)
    return SQLExecutor(engine, settings, pool)


# ---------------------------------------------------------------------------
# SQLite — interrupt() must kill a runaway recursive CTE
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sqlite_interrupt_kills_long_query():
    """A recursive CTE that would never finish must be killed by the timer.

    Tests ``_run_query`` directly so the threading.Timer-driven interrupt is
    isolated from the asyncio.wait_for fallback in ``execute``.  The Timer
    inside ``_run_query`` calls ``raw_conn.interrupt()``; sqlite3 raises
    ``OperationalError("interrupted")``, which propagates out as the
    server-side cancellation we care about.
    """
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        engine = create_engine(f"sqlite:///{db_path}")
        executor = _make_executor(engine, timeout_seconds=0.5)

        # Recursive CTE walking 1..1e9 — would take far longer than 0.5 s.
        runaway_sql = (
            "WITH RECURSIVE r(n) AS ("
            "  SELECT 1 UNION ALL SELECT n + 1 FROM r WHERE n < 1000000000"
            ") SELECT count(*) FROM r"
        )
        start = time.monotonic()
        with pytest.raises((sqlite3.OperationalError, OperationalError)) as excinfo:
            executor._run_query(runaway_sql)
        elapsed = time.monotonic() - start

        # Interrupt should fire well before the query would have finished naturally.
        assert elapsed < 5.0, f"Took {elapsed:.2f}s; expected interrupt-driven cancel"
        assert "interrupted" in str(excinfo.value).lower()
        engine.dispose()
    finally:
        threading.Event().wait(0.05)
        try:
            os.unlink(db_path)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# PostgreSQL — SET LOCAL statement_timeout must trigger server-side cancel
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_postgres_statement_timeout_is_server_side():
    """``SET LOCAL statement_timeout`` must make Postgres cancel pg_sleep server-side.

    Skipped automatically if no Postgres URL is exported in ``DATABASE_URL``.
    """
    pg_url = os.environ.get("DATABASE_URL", "")
    if not pg_url.startswith("postgresql"):
        pytest.skip("No PostgreSQL DATABASE_URL set; cannot exercise server-side cancellation.")

    engine = create_engine(pg_url, pool_pre_ping=True)
    try:
        executor = _make_executor(engine, timeout_seconds=1.0)

        # pg_sleep(5) is far longer than 1s — Postgres should kill it from inside.
        with pytest.raises(OperationalError) as excinfo:
            await executor.execute("SELECT pg_sleep(5)")
        # The orig psycopg2 exception message contains "statement timeout".
        orig_msg = str(getattr(excinfo.value, "orig", excinfo.value)).lower()
        assert "statement timeout" in orig_msg, (
            f"Expected server-side cancellation; got: {orig_msg!r}"
        )
    finally:
        engine.dispose()
