"""Unit tests for SQLValidator — no real database required."""

from unittest.mock import MagicMock

import pytest

from src.core.sql_validator import SQLValidator, ValidationResult, _has_top_level_limit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validator(tables: list[str] | None = None) -> SQLValidator:
    """Return a SQLValidator backed by a mock SchemaInspector."""
    inspector = MagicMock()
    inspector.get_table_names.return_value = (
        tables if tables is not None else ["users", "orders", "products", "order_items"]
    )
    return SQLValidator(inspector)


# ---------------------------------------------------------------------------
# Check 1: forbidden write / DDL operations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO users (name) VALUES ('x')",
        "UPDATE users SET name = 'x' WHERE id = 1",
        "DELETE FROM users WHERE id = 1",
        "DROP TABLE users",
        "DROP TABLE IF EXISTS users",
        "ALTER TABLE users ADD COLUMN age INTEGER",
        "CREATE TABLE foo (id INTEGER)",
        "CREATE INDEX idx ON users (name)",
        "TRUNCATE TABLE users",
        "TRUNCATE users",
        "MERGE INTO users USING src ON users.id = src.id WHEN MATCHED THEN UPDATE SET name = src.name",
        "GRANT SELECT ON users TO public",
        "REVOKE SELECT ON users FROM public",
        "EXEC sp_something",
        "EXECUTE sp_something",
    ],
)
def test_write_operations_are_rejected(sql):
    v = _validator()
    result = v.validate(sql)
    assert result.is_valid is False
    assert "not allowed" in result.error.lower()


def test_write_check_is_case_insensitive():
    v = _validator()
    result = v.validate("insert into users (name) values ('x')")
    assert result.is_valid is False


def test_plain_select_is_allowed():
    v = _validator()
    result = v.validate("SELECT id, name FROM users LIMIT 10")
    assert result.is_valid is True


def test_select_with_subquery_allowed():
    v = _validator()
    result = v.validate(
        "SELECT u.name FROM users u WHERE u.id IN (SELECT user_id FROM orders LIMIT 5)"
    )
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# Check 2: table existence
# ---------------------------------------------------------------------------


def test_unknown_table_is_rejected():
    v = _validator(tables=["users"])
    result = v.validate("SELECT * FROM nonexistent_table LIMIT 10")
    assert result.is_valid is False
    assert "nonexistent_table" in result.error


def test_known_table_passes():
    v = _validator(tables=["users"])
    result = v.validate("SELECT id FROM users LIMIT 5")
    assert result.is_valid is True


def test_join_with_unknown_table_rejected():
    v = _validator(tables=["users"])
    result = v.validate("SELECT u.id FROM users u JOIN ghost g ON u.id = g.user_id LIMIT 10")
    assert result.is_valid is False
    assert "ghost" in result.error


def test_join_with_known_tables_passes():
    v = _validator()
    result = v.validate(
        "SELECT u.name, o.status FROM users u JOIN orders o ON u.id = o.user_id LIMIT 10"
    )
    assert result.is_valid is True


def test_cte_alias_not_flagged_as_missing_table():
    """A CTE defined in a WITH clause should not be treated as a DB table."""
    v = _validator()
    result = v.validate(
        "WITH recent AS (SELECT id FROM orders WHERE status = 'pending') "
        "SELECT * FROM recent LIMIT 10"
    )
    assert result.is_valid is True


def test_subquery_alias_not_flagged_as_missing_table():
    """An inline subquery alias should not be treated as a DB table."""
    v = _validator()
    result = v.validate("SELECT sub.total FROM (SELECT COUNT(*) AS total FROM users) AS sub")
    assert result.is_valid is True


# ---------------------------------------------------------------------------
# Check 3: LIMIT auto-injection
# ---------------------------------------------------------------------------


def test_limit_injected_for_plain_select():
    v = _validator()
    result = v.validate("SELECT id, name FROM users")
    assert result.is_valid is True
    assert result.warning is not None
    assert result.modified_sql is not None
    assert "LIMIT 100" in result.modified_sql


def test_limit_not_injected_when_limit_already_present():
    v = _validator()
    result = v.validate("SELECT id FROM users LIMIT 50")
    assert result.is_valid is True
    assert result.modified_sql is None


def test_limit_not_injected_for_group_by():
    v = _validator()
    result = v.validate("SELECT status, COUNT(*) FROM orders GROUP BY status")
    assert result.is_valid is True
    assert result.modified_sql is None


def test_limit_not_injected_for_count():
    v = _validator()
    result = v.validate("SELECT COUNT(*) FROM users")
    assert result.is_valid is True
    assert result.modified_sql is None


def test_limit_not_injected_for_sum():
    v = _validator()
    result = v.validate("SELECT SUM(total_amount) FROM orders")
    assert result.is_valid is True
    assert result.modified_sql is None


def test_limit_not_injected_for_avg():
    v = _validator()
    result = v.validate("SELECT AVG(total_amount) FROM orders")
    assert result.is_valid is True
    assert result.modified_sql is None


def test_limit_not_injected_for_max():
    v = _validator()
    result = v.validate("SELECT MAX(total_amount) FROM orders")
    assert result.is_valid is True
    assert result.modified_sql is None


def test_limit_not_injected_for_min():
    v = _validator()
    result = v.validate("SELECT MIN(total_amount) FROM orders")
    assert result.is_valid is True
    assert result.modified_sql is None


def test_limit_injected_when_limit_only_in_subquery():
    """LIMIT inside a subquery must not suppress injection on the outer query."""
    v = _validator()
    result = v.validate("SELECT * FROM (SELECT id FROM users LIMIT 5) AS sub")
    assert result.is_valid is True
    assert result.modified_sql is not None
    assert "LIMIT 100" in result.modified_sql


def test_limit_injection_strips_trailing_semicolon_before_appending():
    """Injected LIMIT should not produce double semicolons."""
    v = _validator()
    result = v.validate("SELECT id FROM users;")
    assert result.modified_sql is not None
    assert ";;" not in result.modified_sql
    assert result.modified_sql.endswith("LIMIT 100;")


def test_all_checks_pass_returns_valid_no_warning():
    v = _validator()
    result = v.validate("SELECT id FROM users LIMIT 10")
    assert result.is_valid is True
    assert result.error is None
    assert result.warning is None
    assert result.modified_sql is None


# ---------------------------------------------------------------------------
# _has_top_level_limit helper
# ---------------------------------------------------------------------------


def test_top_level_limit_detected():
    assert _has_top_level_limit("SELECT id FROM users LIMIT 10") is True


def test_top_level_limit_case_insensitive():
    assert _has_top_level_limit("SELECT id FROM users limit 10") is True


def test_subquery_limit_not_detected_as_top_level():
    assert _has_top_level_limit("SELECT * FROM (SELECT id FROM users LIMIT 5) AS s") is False


def test_no_limit_returns_false():
    assert _has_top_level_limit("SELECT id FROM users") is False


def test_limit_in_column_name_not_detected():
    """'limited_stock' must not be confused with the LIMIT keyword."""
    assert _has_top_level_limit("SELECT limited_stock FROM products") is False


# ---------------------------------------------------------------------------
# ValidationResult dataclass defaults
# ---------------------------------------------------------------------------


def test_validation_result_defaults():
    r = ValidationResult(is_valid=True)
    assert r.error is None
    assert r.warning is None
    assert r.modified_sql is None
