"""Persistent query history log keyed by user and API key."""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import Engine, event, func
from sqlalchemy.orm import Session

from src.auth.user_store import QueryHistory, User


@dataclass(frozen=True)
class AggregateStats:
    total: int
    errors: int
    p50_duration_ms: int | None
    p95_duration_ms: int | None


@dataclass(frozen=True)
class DailyCount:
    date: str  # YYYY-MM-DD (UTC)
    total: int
    errors: int


_MAX_PERCENTILE_SAMPLES = 50_000


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

    def get_aggregate_stats_today(self) -> AggregateStats:
        """Return total/error counts and p50/p95 duration for queries logged today (UTC).

        Percentiles are computed in Python over up to _MAX_PERCENTILE_SAMPLES rows.
        For MVP traffic on SQLite this is safe; revisit once query_history exceeds ~1M rows.
        """
        start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        with Session(self._engine) as session:
            total = (
                session.query(func.count(QueryHistory.id))
                .filter(QueryHistory.timestamp >= start)
                .scalar()
                or 0
            )
            errors = (
                session.query(func.count(QueryHistory.id))
                .filter(QueryHistory.timestamp >= start, QueryHistory.success.is_(False))
                .scalar()
                or 0
            )
            if total == 0:
                return AggregateStats(total=0, errors=0, p50_duration_ms=None, p95_duration_ms=None)

            # Do NOT order by duration here: `ORDER BY duration_ms ASC LIMIT N`
            # would keep the N *fastest* rows once a day exceeds N, biasing p95
            # sharply low. Take an unordered slice (≈ a sample) and sort in
            # Python so the percentiles reflect the whole day's distribution.
            rows = (
                session.query(QueryHistory.duration_ms)
                .filter(QueryHistory.timestamp >= start)
                .limit(_MAX_PERCENTILE_SAMPLES)
                .all()
            )
            durations = sorted(int(r[0]) for r in rows if r[0] is not None)

        if not durations:
            return AggregateStats(
                total=int(total), errors=int(errors), p50_duration_ms=None, p95_duration_ms=None
            )

        def _pct(values: list[int], p: float) -> int:
            idx = max(0, min(len(values) - 1, int(round((p / 100.0) * (len(values) - 1)))))
            return values[idx]

        return AggregateStats(
            total=int(total),
            errors=int(errors),
            p50_duration_ms=_pct(durations, 50),
            p95_duration_ms=_pct(durations, 95),
        )

    def get_daily_counts(self, days: int = 14) -> list[DailyCount]:
        """Return per-day query counts for the last `days` days, oldest first.

        Days with zero traffic are still emitted (total=0, errors=0).
        """
        if days <= 0:
            return []
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days - 1)

        with Session(self._engine) as session:
            rows = (
                session.query(func.date(QueryHistory.timestamp), func.count(QueryHistory.id))
                .filter(QueryHistory.timestamp >= start)
                .group_by(func.date(QueryHistory.timestamp))
                .all()
            )
            error_rows = (
                session.query(func.date(QueryHistory.timestamp), func.count(QueryHistory.id))
                .filter(QueryHistory.timestamp >= start, QueryHistory.success.is_(False))
                .group_by(func.date(QueryHistory.timestamp))
                .all()
            )

        total_map: dict[str, int] = {}
        for date_val, total in rows:
            key = str(date_val) if not isinstance(date_val, str) else date_val
            # Normalize to YYYY-MM-DD
            if "T" in key or " " in key:
                key = key.split("T")[0].split(" ")[0]
            total_map[key] = int(total)

        error_map: dict[str, int] = {}
        for date_val, errors in error_rows:
            key = str(date_val) if not isinstance(date_val, str) else date_val
            if "T" in key or " " in key:
                key = key.split("T")[0].split(" ")[0]
            error_map[key] = int(errors)

        out: list[DailyCount] = []
        for offset in range(days):
            day = (start + timedelta(days=offset)).date().isoformat()
            out.append(
                DailyCount(date=day, total=total_map.get(day, 0), errors=error_map.get(day, 0))
            )
        return out

    def list_queries_admin(
        self,
        *,
        user_id: str | None = None,
        success: bool | None = None,
        error_code: str | None = None,
        since: datetime | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[list[dict[str, object]], int]:
        """Cross-user paginated query history. Returns (items, total).

        Items include the user's email so the admin UI need not make a second lookup.
        """
        with Session(self._engine) as session:
            base = session.query(QueryHistory)
            if user_id:
                base = base.filter(QueryHistory.user_id == user_id)
            if success is not None:
                base = base.filter(QueryHistory.success.is_(success))
            if error_code:
                base = base.filter(QueryHistory.error_code == error_code)
            if since is not None:
                base = base.filter(QueryHistory.timestamp >= since)

            total = base.count()

            rows = base.order_by(QueryHistory.id.desc()).limit(limit).offset(offset).all()
            user_ids = list({str(r.user_id) for r in rows})
            email_map: dict[str, str] = {}
            if user_ids:
                user_rows = session.query(User.id, User.email).filter(User.id.in_(user_ids)).all()
                email_map = {str(uid): str(email) for uid, email in user_rows}

            items: list[dict[str, object]] = []
            for r in rows:
                items.append(
                    {
                        "id": r.id,
                        "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                        "user_id": r.user_id,
                        "user_email": email_map.get(str(r.user_id)),
                        "api_key_id": r.api_key_id,
                        "question": r.question,
                        "sql": r.sql,
                        "success": r.success,
                        "row_count": r.row_count,
                        "duration_ms": r.duration_ms,
                        "error": r.error,
                        "error_code": r.error_code,
                        "attempts": r.attempts,
                    }
                )
            return items, int(total)

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
