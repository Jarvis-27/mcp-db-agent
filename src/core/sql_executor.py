"""SQL execution layer — runs validated queries against the database."""

import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial

from sqlalchemy import Engine, text

from src.core.observability import get_tracer, should_capture_sql

_tracer = get_tracer(__name__)


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
        with _tracer.start_as_current_span("db.execute") as span:
            span.set_attribute("db.system", self._engine.dialect.name)
            span.set_attribute("db.statement.hash", hashlib.sha256(sql.encode()).hexdigest()[:16])
            if should_capture_sql():
                span.set_attribute("db.statement", sql)
            loop = asyncio.get_running_loop()
            rows = await asyncio.wait_for(
                loop.run_in_executor(self._pool, partial(self._run_query, sql)),
                timeout=float(self._timeout),
            )
            span.set_attribute("db.rows_affected", len(rows))
            return rows

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
