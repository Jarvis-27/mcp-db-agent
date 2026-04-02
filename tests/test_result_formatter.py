"""Unit tests for ResultFormatter."""

import datetime
import decimal
import json

import pytest

from src.core.result_formatter import ResultFormatter


@pytest.fixture
def fmt():
    return ResultFormatter()


# ---------------------------------------------------------------------------
# format() — success path
# ---------------------------------------------------------------------------


def test_format_basic(fmt):
    rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
    out = json.loads(fmt.format("SELECT * FROM users LIMIT 2;", rows, attempts=1))

    assert out["query"] == "SELECT * FROM users LIMIT 2;"
    assert out["row_count"] == 2
    assert out["columns"] == ["id", "name"]
    assert out["data"] == rows
    assert out["attempts"] == 1


def test_format_empty_rows(fmt):
    out = json.loads(fmt.format("SELECT * FROM users LIMIT 5;", [], attempts=1))

    assert out["row_count"] == 0
    assert out["columns"] == []
    assert out["data"] == []


def test_format_caps_data_at_100_rows(fmt):
    rows = [{"id": i} for i in range(150)]
    out = json.loads(fmt.format("SELECT id FROM users;", rows, attempts=1))

    assert out["row_count"] == 150   # reports actual count
    assert len(out["data"]) == 100   # but only sends first 100


def test_format_attempts_preserved(fmt):
    out = json.loads(fmt.format("SELECT 1;", [], attempts=3))
    assert out["attempts"] == 3


# ---------------------------------------------------------------------------
# format() — custom JSON serialization
# ---------------------------------------------------------------------------


def test_format_serializes_datetime(fmt):
    dt = datetime.datetime(2024, 3, 15, 10, 30, 0)
    rows = [{"created_at": dt}]
    out = json.loads(fmt.format("SELECT created_at FROM orders;", rows, attempts=1))

    assert out["data"][0]["created_at"] == "2024-03-15T10:30:00"


def test_format_serializes_date(fmt):
    d = datetime.date(2024, 6, 1)
    rows = [{"order_date": d}]
    out = json.loads(fmt.format("SELECT order_date FROM orders;", rows, attempts=1))

    assert out["data"][0]["order_date"] == "2024-06-01"


def test_format_serializes_decimal(fmt):
    rows = [{"price": decimal.Decimal("19.99")}]
    out = json.loads(fmt.format("SELECT price FROM products;", rows, attempts=1))

    assert out["data"][0]["price"] == pytest.approx(19.99)


# ---------------------------------------------------------------------------
# format_error() — failure path
# ---------------------------------------------------------------------------


def test_format_error_basic(fmt):
    errors = ["Table 'x' does not exist", "syntax error near 'FORM'"]
    out = json.loads(
        fmt.format_error(
            error=errors[-1],
            last_sql="SELECT * FORM x",
            errors=errors,
        )
    )

    assert out["error"] == "syntax error near 'FORM'"
    assert out["attempted_sql"] == "SELECT * FORM x"
    assert out["errors"] == errors
    assert "suggestion" in out
    assert len(out["suggestion"]) > 0


def test_format_error_suggestion_mentions_describe_schema(fmt):
    out = json.loads(fmt.format_error("some error", "SELECT 1", []))
    assert "describe_schema" in out["suggestion"]


def test_format_error_empty_errors_list(fmt):
    out = json.loads(fmt.format_error("timed out", "SELECT 1", []))
    assert out["errors"] == []
