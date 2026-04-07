"""Persistent query history log backed by a dedicated SQLite database."""

import datetime
from pathlib import Path

from sqlalchemy import Boolean, Column, DateTime, Integer, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

# Default log DB sits next to the project root so it is easy to find and inspect.
_DEFAULT_DB_PATH = str(Path(__file__).parent.parent.parent / "query_log.db")


class _Base(DeclarativeBase):
    pass


class _QueryHistory(_Base):
    __tablename__ = "query_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False)
    question = Column(Text, nullable=False)
    sql = Column(Text, nullable=False)
    success = Column(Boolean, nullable=False)
    row_count = Column(Integer, nullable=True)
    attempts = Column(Integer, nullable=False)
    duration_ms = Column(Integer, nullable=False)
    error = Column(Text, nullable=True)


class QueryLog:
    """Logs every query attempt and its outcome to a dedicated SQLite database.

    Uses a *separate* engine so it never interferes with the user's database
    connection and works regardless of which backend (PostgreSQL or SQLite)
    the main database uses.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._engine = create_engine(f"sqlite:///{db_path}")
        _Base.metadata.create_all(self._engine)

    def log_query(
        self,
        question: str,
        sql: str,
        success: bool,
        row_count: int,
        attempts: int,
        duration_ms: int,
        error: str | None,
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
        """
        with Session(self._engine) as session:
            entry = _QueryHistory(
                timestamp=datetime.datetime.utcnow(),
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

    def get_recent_queries(self, limit: int = 10) -> list[dict[str, object]]:
        """Return the *limit* most recent query records, newest first.

        Args:
            limit: Maximum number of records to return.

        Returns:
            List of dicts with keys: id, timestamp, question, sql, success,
            row_count, attempts, duration_ms, error.
        """
        with Session(self._engine) as session:
            rows = (
                session.query(_QueryHistory)
                .order_by(_QueryHistory.id.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "id": r.id,
                    "timestamp": r.timestamp.isoformat() if r.timestamp else None,
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
