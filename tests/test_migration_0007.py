"""Tests for Alembic revision 0007 single-user cutover safeguards."""

from __future__ import annotations

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0007_single_user_schema.py"
)


def _load_migration_module():
    spec = spec_from_file_location("migration_0007_single_user_schema", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _DummyBatchAlter:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def add_column(self, *args, **kwargs) -> None:
        return None

    def drop_column(self, *args, **kwargs) -> None:
        return None

    def alter_column(self, *args, **kwargs) -> None:
        return None

    def create_foreign_key(self, *args, **kwargs) -> None:
        return None

    def create_index(self, *args, **kwargs) -> None:
        return None

    def drop_index(self, *args, **kwargs) -> None:
        return None


def _result(rows):
    result = MagicMock()
    result.fetchall.return_value = rows
    return result


def _make_connection(rows_by_sql: dict[str, list[tuple]]) -> MagicMock:
    conn = MagicMock()

    def _execute(statement):
        sql = str(statement)
        for needle, rows in rows_by_sql.items():
            if needle in sql:
                return _result(rows)
        return _result([])

    conn.execute.side_effect = _execute
    conn.commit = MagicMock()
    return conn


def _make_op(conn: MagicMock) -> SimpleNamespace:
    return SimpleNamespace(
        get_bind=MagicMock(return_value=conn),
        create_table=MagicMock(),
        create_index=MagicMock(),
        drop_table=MagicMock(),
        batch_alter_table=MagicMock(side_effect=lambda *args, **kwargs: _DummyBatchAlter()),
    )


def test_upgrade_fails_fast_on_duplicate_owner_emails(monkeypatch):
    migration = _load_migration_module()
    conn = _make_connection({"GROUP BY m.email": [("dup@example.com",)]})
    op = _make_op(conn)
    monkeypatch.setattr(migration, "op", op)

    with pytest.raises(RuntimeError, match="duplicate email"):
        migration.upgrade()

    op.create_table.assert_not_called()
    conn.commit.assert_not_called()


def test_upgrade_does_not_commit_mid_migration(monkeypatch):
    migration = _load_migration_module()
    conn = _make_connection({})
    op = _make_op(conn)
    monkeypatch.setattr(migration, "op", op)

    migration.upgrade()

    conn.commit.assert_not_called()
    assert op.create_table.call_count >= 2
    assert op.drop_table.call_count == 4
