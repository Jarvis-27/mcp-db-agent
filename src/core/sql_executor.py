"""SQL execution layer — runs validated queries against the database."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from sqlalchemy import Engine, text


class SQLExecutor:
    def __init__(self, engine: Engine, settings, pool: ThreadPoolExecutor) -> None:
        self._engine = engine
        self._timeout = settings.query_timeout_seconds
        self._pool = pool

    async def execute(self, sql: str) -> list[dict[str, object]]:
        """Execute validated SQL and return results as a list of row dicts.

        Runs the synchronous SQLAlchemy call in the injected thread pool so
        async callers are not blocked. Exceptions are intentionally not caught
        here — the SelfCorrector layer is responsible for retries.
        """
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(self._pool, partial(self._run_query, sql)),
            timeout=float(self._timeout),
        )

    def _run_query(self, sql: str) -> list[dict[str, object]]:
        dialect_name = self._engine.dialect.name
        # PostgreSQL benefits from REPEATABLE READ to prevent dirty reads.
        # SQLite uses the default isolation (autocommit-compatible for reads).
        exec_opts: dict[str, str] = (
            {"isolation_level": "REPEATABLE READ"} if dialect_name == "postgresql" else {}
        )
        with self._engine.connect() as conn:
            if exec_opts:
                conn = conn.execution_options(**exec_opts)

            if dialect_name == "postgresql":
                # statement_timeout was removed from engine connect_args to support
                # pooled providers (e.g. Neon) that reject startup options.
                # Set it here, per connection, after checkout.
                timeout_ms = int(float(self._timeout) * 1000)
                conn.execute(text(f"SET LOCAL statement_timeout = {timeout_ms}"))

            timer: threading.Timer | None = None
            if dialect_name == "sqlite":
                # PostgreSQL handles timeouts server-side via statement_timeout (set per
                # connection above via SET LOCAL). SQLite has no server-side mechanism,
                # so we schedule interrupt() on the raw DBAPI connection instead.
                # interrupt() causes any in-progress sqlite3 operation to raise
                # OperationalError("interrupted"), which exits the thread cleanly.
                raw_conn = conn.connection.driver_connection
                if raw_conn is None:
                    raise RuntimeError("SQLite driver connection is not available.")
                timer = threading.Timer(float(self._timeout), raw_conn.interrupt)
                timer.daemon = True
                timer.start()

            try:
                result = conn.execute(text(sql))
                return [dict(row) for row in result.mappings().all()]
            finally:
                if timer is not None:
                    timer.cancel()
