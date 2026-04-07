"""SQL execution layer — runs validated queries against the database."""

import asyncio
from functools import partial

from sqlalchemy import Engine, text

from src.config import Settings


class SQLExecutor:
    def __init__(self, engine: Engine, settings: Settings) -> None:
        self._engine = engine
        self._timeout = settings.query_timeout_seconds

    async def execute(self, sql: str) -> list[dict[str, object]]:
        """Execute validated SQL and return results as a list of row dicts.

        Runs the synchronous SQLAlchemy call in a thread-pool executor so
        async callers are not blocked. Exceptions are intentionally not caught
        here — the SelfCorrector layer is responsible for retries.
        """
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, partial(self._run_query, sql)),
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
            result = conn.execute(text(sql))
            return [dict(row) for row in result.mappings().all()]
