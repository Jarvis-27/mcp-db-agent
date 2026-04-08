"""Persistent query history log — stores every query attempt and outcome."""

from datetime import UTC, datetime

from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

# Import the model from user_store where it is co-located with the Alembic Base
from src.auth.user_store import QueryHistory


def _enable_wal(dbapi_conn, _connection_record) -> None:
    """Enable WAL mode + sane pragmas for SQLite.

    WAL allows concurrent readers and one writer without blocking — important
    when the auth DB and query log share the same SQLite file.
    """
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


class QueryLog:
    """Logs every query attempt and its outcome to the auth database.

    Constructor accepts an injected Engine so this class can share the auth DB
    engine without opening a second connection.  Schema is managed by Alembic —
    this class does NOT call create_all.
    """

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", _enable_wal)

    def log_query(
        self,
        question: str,
        sql: str,
        success: bool,
        row_count: int,
        attempts: int,
        duration_ms: int,
        error: str | None,
        user_id: str,
    ) -> None:
        """Insert a record into ``query_history``.

        Args:
            question: Original natural-language question from the MCP client.
            sql: Last SQL string that was attempted.
            success: ``True`` if execution succeeded.
            row_count: Number of rows returned (0 on failure).
            attempts: Number of generation/correction cycles consumed.
            duration_ms: Wall-clock time for the full pipeline in milliseconds.
            error: Final error message, or ``None`` on success.
            user_id: Non-nullable. Use ``"__stdio__"`` in single-user stdio mode.
        """
        if not user_id:
            raise ValueError("user_id is required and must not be empty")

        with Session(self._engine) as session:
            entry = QueryHistory(
                timestamp=datetime.now(UTC),
                user_id=user_id,
                question=question,
                sql=sql,
                success=success,
                row_count=row_count,
                attempts=attempts,
                duration_ms=duration_ms,
                error=error,
            )
            session.add(entry)
            session.commit()

    def get_recent_queries(self, limit: int = 10, user_id: str = "") -> list[dict[str, object]]:
        """Return the *limit* most recent query records for *user_id*, newest first.

        Args:
            limit: Maximum number of records to return.
            user_id: Non-nullable. Pass ``"__stdio__"`` in single-user stdio mode.

        Raises:
            ValueError: If user_id is empty.
        """
        if not user_id:
            raise ValueError("user_id is required and must not be empty")

        with Session(self._engine) as session:
            rows = (
                session.query(QueryHistory)
                .filter(QueryHistory.user_id == user_id)
                .order_by(QueryHistory.id.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                    "user_id": r.user_id,
                    "question": r.question,
                    "sql": r.sql,
                    "success": r.success,
                    "row_count": r.row_count,
                    "attempts": r.attempts,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                }
                for r in rows
            ]
