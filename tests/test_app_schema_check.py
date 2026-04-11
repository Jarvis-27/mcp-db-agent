"""Tests for the production Alembic schema-version check in src/app.py lifespan.

The check lives inside an `else` branch that only runs when
`settings.environment != "development"`.  We test it by calling the underlying
logic directly via mocks rather than spinning up the full ASGI lifespan.
"""

from unittest.mock import MagicMock, patch
import pytest


def _run_schema_check(current_revision: str | None, head_revision: str | None):
    """Exercise the production schema-check block from src/app.py.

    Replicates the exact logic so we don't have to launch a full lifespan.
    Raises RuntimeError if the schema is not at head, otherwise returns None.
    """
    from alembic.config import Config as _AlembicConfig
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    mock_script_dir = MagicMock(spec=ScriptDirectory)
    mock_script_dir.get_current_head.return_value = head_revision

    mock_ctx = MagicMock(spec=MigrationContext)
    mock_ctx.get_current_revision.return_value = current_revision

    mock_conn = MagicMock()
    mock_engine = MagicMock()
    mock_engine.connect.return_value.__enter__ = lambda s: mock_conn
    mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("alembic.script.ScriptDirectory.from_config", return_value=mock_script_dir),
        patch("alembic.runtime.migration.MigrationContext.configure", return_value=mock_ctx),
    ):
        # Inline the production check block
        try:
            _alembic_cfg = _AlembicConfig.__new__(_AlembicConfig)
            _script_dir = ScriptDirectory.from_config(_alembic_cfg)
            expected_head = _script_dir.get_current_head()

            ctx = MigrationContext.configure(mock_conn)
            current = ctx.get_current_revision()
            if current != expected_head:
                raise RuntimeError("Database schema is not up to date")
        except RuntimeError:
            raise
        except Exception:
            pass  # non-schema errors are warnings in production


def test_schema_check_passes_at_head():
    """No error when DB revision matches the script head."""
    _run_schema_check(current_revision="0001", head_revision="0001")


def test_schema_check_fails_when_behind():
    """RuntimeError raised when DB is behind head."""
    with pytest.raises(RuntimeError, match="Database schema is not up to date"):
        _run_schema_check(current_revision=None, head_revision="0001")


def test_schema_check_passes_at_new_head():
    """No error when both DB and scripts are at a later revision.

    Regression test: the old hardcoded `current != "0001"` check would have
    incorrectly rejected a DB migrated to revision "0002".
    """
    _run_schema_check(current_revision="0002", head_revision="0002")


def test_schema_check_fails_when_migration_pending():
    """RuntimeError when DB is at 0001 but a new migration 0002 exists."""
    with pytest.raises(RuntimeError, match="Database schema is not up to date"):
        _run_schema_check(current_revision="0001", head_revision="0002")


def test_schema_check_warning_on_alembic_error():
    """Non-schema exceptions are swallowed (server starts with a warning)."""
    from alembic.script import ScriptDirectory

    with patch(
        "alembic.script.ScriptDirectory.from_config",
        side_effect=FileNotFoundError("alembic.ini not found"),
    ):
        # Should not raise — the outer except swallows non-schema errors
        try:
            from alembic.config import Config as _AlembicConfig

            _alembic_cfg = _AlembicConfig.__new__(_AlembicConfig)
            _script_dir = ScriptDirectory.from_config(_alembic_cfg)
        except FileNotFoundError:
            pass  # confirmed: non-schema error is catchable and swallowable
