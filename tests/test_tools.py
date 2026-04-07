"""Unit tests for all four MCP tools (no real DB or LLM required)."""

import json
from unittest.mock import AsyncMock, MagicMock

from src.tools.ask_database import ask_database
from src.tools.describe_schema import describe_schema
from src.tools.get_sample_data import get_sample_data
from src.tools.list_tables import list_tables
from src.core.result_formatter import ResultFormatter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_DEFAULT_TABLES = ["users", "orders"]
_DEFAULT_COUNTS = [
    {"table_name": "users", "row_count": 500},
    {"table_name": "orders", "row_count": 2000},
]
_DEFAULT_ROWS = [{"id": 1, "name": "Alice"}]


def _inspector(tables=None, counts=None, detail="TABLE: users\n  id INTEGER", rows=None):
    insp = MagicMock()
    insp.get_table_names.return_value = _DEFAULT_TABLES if tables is None else tables
    insp.get_tables_with_counts.return_value = _DEFAULT_COUNTS if counts is None else counts
    insp.get_table_detail.return_value = detail
    insp.get_sample_rows.return_value = _DEFAULT_ROWS if rows is None else rows
    return insp


# ---------------------------------------------------------------------------
# list_tables
# ---------------------------------------------------------------------------


def test_list_tables_returns_json():
    out = json.loads(list_tables(_inspector()))
    assert isinstance(out, list)
    assert out[0]["table_name"] == "users"
    assert out[0]["row_count"] == 500


def test_list_tables_empty_database():
    insp = _inspector(tables=[], counts=[])
    out = json.loads(list_tables(insp))
    assert out == []


# ---------------------------------------------------------------------------
# describe_schema
# ---------------------------------------------------------------------------


def test_describe_schema_known_table():
    insp = _inspector()
    result = describe_schema("users", insp)
    assert "TABLE: users" in result
    insp.get_table_detail.assert_called_once_with("users")


def test_describe_schema_unknown_table_returns_error_json():
    insp = _inspector(tables=["users"])
    out = json.loads(describe_schema("nonexistent", insp))
    assert "error" in out
    assert "nonexistent" in out["error"]
    assert "list_tables" in out["error"]
    insp.get_table_detail.assert_not_called()


def test_describe_schema_empty_string_table_name():
    insp = _inspector(tables=["users"])
    out = json.loads(describe_schema("", insp))
    assert "error" in out


# ---------------------------------------------------------------------------
# get_sample_data
# ---------------------------------------------------------------------------


def test_get_sample_data_returns_rows():
    insp = _inspector(rows=[{"id": 1}, {"id": 2}])
    out = json.loads(get_sample_data("users", insp))
    assert len(out) == 2


def test_get_sample_data_unknown_table_returns_error_json():
    insp = _inspector(tables=["users"])
    out = json.loads(get_sample_data("nonexistent", insp))
    assert "error" in out
    assert "list_tables" in out["error"]
    insp.get_sample_rows.assert_not_called()


def test_get_sample_data_limit_capped_at_20():
    insp = _inspector()
    get_sample_data("users", insp, limit=50)
    insp.get_sample_rows.assert_called_once_with("users", 20)


def test_get_sample_data_negative_limit_clamped_to_1():
    insp = _inspector()
    get_sample_data("users", insp, limit=-5)
    insp.get_sample_rows.assert_called_once_with("users", 1)


def test_get_sample_data_zero_limit_clamped_to_1():
    insp = _inspector()
    get_sample_data("users", insp, limit=0)
    insp.get_sample_rows.assert_called_once_with("users", 1)


def test_get_sample_data_default_limit_is_5():
    insp = _inspector()
    get_sample_data("users", insp)
    insp.get_sample_rows.assert_called_once_with("users", 5)


# ---------------------------------------------------------------------------
# ask_database
# ---------------------------------------------------------------------------


def _make_corrector(success: bool, sql="SELECT 1", data=None, errors=None, attempts=1):
    c = MagicMock()
    c.execute_with_correction = AsyncMock(
        return_value={
            "success": success,
            "sql": sql,
            "data": data or [],
            "attempts": attempts,
            "errors": errors or [],
        }
    )
    return c


async def test_ask_database_success_path():
    rows = [{"id": 1, "name": "Alice"}]
    corrector = _make_corrector(success=True, sql="SELECT id, name FROM users LIMIT 5;", data=rows)
    fmt = ResultFormatter()

    out = json.loads(await ask_database("List users", corrector, fmt, "sqlite"))

    assert out["query"] == "SELECT id, name FROM users LIMIT 5;"
    assert out["data"] == rows
    assert out["attempts"] == 1


async def test_ask_database_failure_path():
    errors = ["Table 'x' does not exist", "syntax error"]
    corrector = _make_corrector(success=False, sql="SELECT * FROM x", errors=errors, attempts=3)
    fmt = ResultFormatter()

    out = json.loads(await ask_database("Bad question", corrector, fmt, "sqlite"))

    assert "error" in out
    assert out["error"] == "syntax error"  # last error
    assert out["errors"] == errors
    assert "suggestion" in out


async def test_ask_database_failure_empty_errors_list():
    """If no errors were recorded, a fallback message should be used."""
    corrector = _make_corrector(success=False, sql="SELECT 1", errors=[])
    fmt = ResultFormatter()

    out = json.loads(await ask_database("??", corrector, fmt))

    assert "error" in out
    assert len(out["error"]) > 0


async def test_ask_database_forwards_dialect():
    corrector = _make_corrector(success=True)
    fmt = MagicMock()
    fmt.format.return_value = (
        '{"query":"SELECT 1","row_count":0,"columns":[],"data":[],"attempts":1}'
    )

    await ask_database("Count users", corrector, fmt, dialect="postgresql")

    corrector.execute_with_correction.assert_awaited_once_with("Count users", "postgresql")
