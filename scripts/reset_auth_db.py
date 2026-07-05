"""Wipe all user-owned rows from the auth database.

Reads ``AUTH_DATABASE_URL`` from your ``.env`` (via src.config.settings) and
clears every row in:

    users, user_sessions, api_keys, query_history,
    billing_webhook_events, verification_tokens

Schema and Alembic version are preserved. Auto-increment counters are reset
(Postgres) or left as-is (SQLite — only `query_history.id` is affected, which
is harmless).

Examples
--------

    # Dry run (default) — print row counts, do not delete.
    uv run python scripts/reset_auth_db.py

    # Actually wipe.
    uv run python scripts/reset_auth_db.py --yes

    # Wipe a different DB (override AUTH_DATABASE_URL just for this command).
    uv run python scripts/reset_auth_db.py --yes --db-url postgresql://...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402

from src.config import settings  # noqa: E402

# Order matters for the SQLite path (no CASCADE there). Children first, parents last.
_TABLES_IN_FK_ORDER = (
    "verification_tokens",
    "billing_webhook_events",
    "query_history",
    "api_keys",
    "user_sessions",
    "users",
)


def _redact(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.password:
            return url.replace(parsed.password, "***")
    except Exception:
        pass
    return url


def _row_counts(engine, tables: tuple[str, ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with engine.connect() as conn:
        for table in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                counts[table] = int(result.scalar() or 0)
            except Exception as exc:
                counts[table] = -1
                print(f"  ! could not count {table}: {exc}", file=sys.stderr)
    return counts


def _truncate_postgres(engine) -> None:
    table_list = ", ".join(_TABLES_IN_FK_ORDER)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE"))


def _delete_sqlite(engine) -> None:
    with engine.begin() as conn:
        for table in _TABLES_IN_FK_ORDER:
            conn.execute(text(f"DELETE FROM {table}"))
        # Reset query_history's autoincrement counter if sqlite_sequence exists.
        conn.execute(text("DELETE FROM sqlite_sequence WHERE name IN ('query_history')"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override AUTH_DATABASE_URL just for this command.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually execute the wipe. Without this flag, prints row counts only.",
    )
    args = parser.parse_args()

    db_url = args.db_url or settings.auth_database_url
    if not db_url:
        print("AUTH_DATABASE_URL is not configured.", file=sys.stderr)
        return 1

    print(f"target: {_redact(db_url)}")

    engine = create_engine(db_url)
    dialect = engine.dialect.name
    print(f"dialect: {dialect}")

    counts_before = _row_counts(engine, _TABLES_IN_FK_ORDER)
    total = sum(c for c in counts_before.values() if c >= 0)
    print()
    print("current row counts:")
    for table in _TABLES_IN_FK_ORDER:
        print(f"  {table:<28} {counts_before[table]:>8}")
    print(f"  {'TOTAL':<28} {total:>8}")
    print()

    if not args.yes:
        print("dry run - pass --yes to actually wipe.")
        return 0

    if total == 0:
        print("nothing to delete.")
        return 0

    if dialect == "postgresql":
        _truncate_postgres(engine)
    elif dialect == "sqlite":
        _delete_sqlite(engine)
    else:
        print(
            f"unsupported dialect {dialect!r}. Add a handler or run TRUNCATE by hand.",
            file=sys.stderr,
        )
        return 2

    counts_after = _row_counts(engine, _TABLES_IN_FK_ORDER)
    remaining = sum(c for c in counts_after.values() if c >= 0)
    print(f"done. {total} rows deleted across {len(_TABLES_IN_FK_ORDER)} tables.")
    if remaining:
        print(f"warning: {remaining} rows still present.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
