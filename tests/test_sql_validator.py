"""Unit tests for SQLValidator — no real database required."""

from unittest.mock import MagicMock

import pytest

from src.core.sql_validator import (
    SQLValidator,
    ValidationResult,
    _first_sql_keyword,
    _has_top_level_limit,
)


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
    # The allowlist check fires first for non-SELECT statements ("Only SELECT
    # queries are allowed"); the DML check fires for writable CTEs ("Write
    # operations are not allowed"). Both contain "allowed".
    assert "allowed" in result.error.lower()


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


def test_limit_injected_when_limit_only_in_string_literal():
    """A literal containing the word LIMIT must not suppress injection."""
    v = _validator()
    result = v.validate("SELECT id FROM users WHERE comment = 'LIMIT 5'")
    assert result.is_valid is True
    assert result.modified_sql is not None
    assert result.modified_sql.endswith("LIMIT 100;")


def test_limit_injected_when_limit_only_in_line_comment():
    """A line comment mentioning LIMIT must not suppress injection."""
    v = _validator()
    result = v.validate("SELECT id FROM users -- LIMIT 5 was here\n")
    assert result.is_valid is True
    assert result.modified_sql is not None
    assert result.modified_sql.endswith("LIMIT 100;")


def test_limit_injected_when_aggregation_token_only_in_string_literal():
    """A literal containing COUNT(* must not be mistaken for an aggregation."""
    v = _validator()
    result = v.validate("SELECT id FROM users WHERE note = 'COUNT(*) of issues'")
    assert result.is_valid is True
    assert result.modified_sql is not None
    assert result.modified_sql.endswith("LIMIT 100;")


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
# Allowlist: statements that previously bypassed the blacklist (Critical #1)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        # COPY — file-read / file-write (plain path, no PROGRAM keyword)
        "COPY users TO '/tmp/out.csv'",
        "COPY users FROM '/etc/passwd'",
        "COPY (SELECT * FROM users) TO '/tmp/out.csv'",
        # CALL — arbitrary stored procedure execution
        "CALL dangerous_procedure()",
        # VACUUM — side-effecting maintenance command
        "VACUUM",
        "VACUUM users",
        # SET — privilege escalation / session hijack
        "SET ROLE postgres",
        "SET search_path TO evil_schema",
        # Other non-SELECT statements that must be denied
        "SHOW search_path",
        "EXPLAIN SELECT id FROM users",
        "DO $$ BEGIN NULL; END $$",
    ],
)
def test_non_select_statements_rejected_by_allowlist(sql):
    """Every statement whose first keyword is not SELECT or WITH must be rejected."""
    v = _validator()
    result = v.validate(sql)
    assert result.is_valid is False
    assert "Only SELECT queries are allowed" in result.error


def test_cte_select_allowed_by_allowlist():
    """WITH … SELECT is a valid read-only CTE and must pass."""
    v = _validator()
    result = v.validate(
        "WITH recent AS (SELECT id FROM orders WHERE status = 'pending') "
        "SELECT * FROM recent LIMIT 10"
    )
    assert result.is_valid is True


def test_writable_cte_rejected_by_dml_check():
    """WITH … DELETE … SELECT must be rejected even though it starts with WITH."""
    v = _validator()
    result = v.validate("WITH d AS (DELETE FROM users WHERE id = 1 RETURNING *) SELECT * FROM d")
    assert result.is_valid is False


# ---------------------------------------------------------------------------
# _first_sql_keyword helper
# ---------------------------------------------------------------------------


def test_first_keyword_select():
    assert _first_sql_keyword("SELECT id FROM users") == "SELECT"


def test_first_keyword_with():
    assert _first_sql_keyword("WITH cte AS (SELECT 1) SELECT * FROM cte") == "WITH"


def test_first_keyword_copy():
    assert _first_sql_keyword("COPY users TO '/tmp/x.csv'") == "COPY"


def test_first_keyword_strips_line_comment():
    assert _first_sql_keyword("-- comment\nSELECT 1") == "SELECT"


def test_first_keyword_strips_block_comment():
    assert _first_sql_keyword("/* comment */ VACUUM") == "VACUUM"


def test_first_keyword_empty():
    assert _first_sql_keyword("   ") == ""


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


# ---------------------------------------------------------------------------
# Forbidden-keyword scan: must not match inside string literals or comments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "literal_word",
    ["merge", "truncate", "exec", "execute", "grant", "revoke"],
)
def test_forbidden_keyword_in_string_literal_does_not_reject(literal_word):
    """A SELECT whose data contains a forbidden keyword must still pass."""
    v = _validator()
    result = v.validate(f"SELECT id FROM users WHERE feedback = '{literal_word} please' LIMIT 5")
    assert result.is_valid is True, result.error


def test_forbidden_keyword_in_block_comment_does_not_reject():
    v = _validator()
    result = v.validate("SELECT id FROM users /* TODO: revoke old keys */ LIMIT 5")
    assert result.is_valid is True, result.error


def test_forbidden_keyword_in_line_comment_does_not_reject():
    v = _validator()
    result = v.validate("SELECT id FROM users -- merge needed\nLIMIT 5")
    assert result.is_valid is True, result.error


def test_escaped_quote_in_string_literal_does_not_unbalance_mask():
    """A '' inside a literal must not leak surrounding text into the scan."""
    v = _validator()
    result = v.validate("SELECT id FROM users WHERE note = 'it''s a merge' LIMIT 5")
    assert result.is_valid is True, result.error


# ---------------------------------------------------------------------------
# Schema-qualified table names: schema.table must not fail existence check
# ---------------------------------------------------------------------------


def test_schema_qualified_table_passes_existence_check():
    v = _validator(tables=["users"])
    result = v.validate("SELECT * FROM public.users LIMIT 5")
    assert result.is_valid is True, result.error


def test_schema_qualified_join_passes_existence_check():
    v = _validator(tables=["users", "orders"])
    result = v.validate(
        "SELECT u.id FROM public.users u JOIN public.orders o ON u.id = o.user_id LIMIT 5"
    )
    assert result.is_valid is True, result.error


def test_schema_qualified_unknown_table_still_rejected():
    """The fix must not weaken existence checking — only the table portion is verified."""
    v = _validator(tables=["users"])
    result = v.validate("SELECT * FROM public.ghost LIMIT 5")
    assert result.is_valid is False
    assert "ghost" in result.error


# ---------------------------------------------------------------------------
# Configurable max_query_rows (G7): auto-inject uses setting + user LIMIT clamp
# ---------------------------------------------------------------------------


def _validator_with_max(max_rows: int, tables: list[str] | None = None) -> SQLValidator:
    inspector = MagicMock()
    inspector.get_table_names.return_value = tables if tables is not None else ["users", "orders"]
    return SQLValidator(inspector, max_query_rows=max_rows)


def test_auto_inject_uses_configured_max():
    v = _validator_with_max(25)
    result = v.validate("SELECT id FROM users")
    assert result.is_valid is True
    assert result.modified_sql is not None
    assert result.modified_sql.endswith("LIMIT 25;")


def test_auto_inject_default_is_100():
    v = _validator()  # default max_query_rows=100
    result = v.validate("SELECT id FROM users")
    assert result.modified_sql is not None
    assert result.modified_sql.endswith("LIMIT 100;")


def test_user_limit_clamped_when_over_max():
    v = _validator_with_max(100)
    result = v.validate("SELECT id FROM users LIMIT 9999")
    assert result.is_valid is True
    assert result.warning is not None
    assert "clamped" in result.warning.lower()
    assert result.modified_sql is not None
    assert "LIMIT 100" in result.modified_sql
    assert "9999" not in result.modified_sql


def test_user_limit_kept_when_under_max():
    v = _validator_with_max(100)
    result = v.validate("SELECT id FROM users LIMIT 50")
    assert result.is_valid is True
    assert result.modified_sql is None  # untouched


def test_user_limit_equal_to_max_kept():
    v = _validator_with_max(100)
    result = v.validate("SELECT id FROM users LIMIT 100")
    assert result.is_valid is True
    assert result.modified_sql is None


def test_clamp_skipped_for_aggregation():
    v = _validator_with_max(100)
    result = v.validate("SELECT COUNT(*) FROM users LIMIT 9999")
    assert result.is_valid is True
    assert result.modified_sql is None  # aggregation: clamp doesn't apply


def test_clamp_preserves_surrounding_sql():
    v = _validator_with_max(50)
    result = v.validate("SELECT id, name FROM users WHERE id > 0 LIMIT 9999")
    assert result.modified_sql is not None
    assert result.modified_sql.startswith("SELECT id, name FROM users WHERE id > 0 LIMIT ")
    assert result.modified_sql.rstrip(";").endswith("LIMIT 50")


def test_clamp_does_not_affect_subquery_limit():
    """A subquery LIMIT is not top-level; auto-inject fires at top instead."""
    v = _validator_with_max(50)
    result = v.validate("SELECT * FROM (SELECT id FROM users LIMIT 9999) AS sub")
    assert result.modified_sql is not None
    # Inner LIMIT 9999 is untouched; outer auto-LIMIT 50 is appended.
    assert "LIMIT 9999" in result.modified_sql
    assert result.modified_sql.endswith("LIMIT 50;")
