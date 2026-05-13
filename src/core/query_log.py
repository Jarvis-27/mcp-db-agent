"""Persistent query history log keyed by user and API key."""

from datetime import UTC, datetime

from sqlalchemy import Engine, event
from sqlalchemy.orm import Session

from src.auth.user_store import QueryHistory


def _enable_wal(dbapi_conn, _connection_record) -> None:
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=5000")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()


class QueryLog:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        if engine.dialect.name == "sqlite":
            event.listen(engine, "connect", _enable_wal)

    def log_query(
        self,
        *,
        question: str,
        sql: str,
        success: bool,
        row_count: int,
        attempts: int,
        duration_ms: int,
        error: str | None,
        user_id: str,
        api_key_id: str | None,
        error_code: str | None = None,
        plan_code: str | None = None,
        daily_count: int | None = None,
        daily_limit: int | None = None,
        warning_level: str | None = None,
    ) -> None:
        if not user_id:
            raise ValueError("user_id is required and must not be empty")

        with Session(self._engine) as session:
            entry = QueryHistory(
                timestamp=datetime.now(UTC),
                user_id=user_id,
                api_key_id=api_key_id,
                question=question,
                sql=sql,
                success=success,
                row_count=row_count,
                attempts=attempts,
                duration_ms=duration_ms,
                error=error,
                error_code=error_code,
                plan_code=plan_code,
                daily_count=daily_count,
                daily_limit=daily_limit,
                warning_level=warning_level,
            )
            session.add(entry)
            session.commit()

    def get_recent_queries(self, limit: int = 10, user_id: str = "") -> list[dict[str, object]]:
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
                    "api_key_id": r.api_key_id,
                    "question": r.question,
                    "sql": r.sql,
                    "success": r.success,
                    "row_count": r.row_count,
                    "attempts": r.attempts,
                    "duration_ms": r.duration_ms,
                    "error": r.error,
                    "error_code": r.error_code,
                    "plan_code": r.plan_code,
                    "daily_count": r.daily_count,
                    "daily_limit": r.daily_limit,
                    "warning_level": r.warning_level,
                }
                for r in rows
            ]
