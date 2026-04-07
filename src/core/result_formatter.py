"""Transforms raw query results into clean, JSON-serializable response dicts."""

import datetime
import decimal
import json


def _json_default(obj: object) -> str | float:
    """Custom serializer for types json.dumps cannot handle by default."""
    if isinstance(obj, datetime.datetime):
        return obj.isoformat()
    if isinstance(obj, datetime.date):
        return obj.isoformat()
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, bytes):
        return obj.hex()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


class ResultFormatter:
    def format(self, sql: str, rows: list[dict[str, object]], attempts: int) -> str:
        """Format successful query results as a JSON string.

        Args:
            sql: The SQL that was executed.
            rows: Raw row dicts returned by SQLExecutor.
            attempts: Number of SelfCorrector loop iterations used.

        Returns:
            JSON string with keys: query, row_count, columns, data, attempts.
        """
        capped = rows[:100]
        result = {
            "query": sql,
            "row_count": len(rows),
            "columns": list(rows[0].keys()) if rows else [],
            "data": capped,
            "attempts": attempts,
        }
        return json.dumps(result, default=_json_default, indent=2)

    def format_error(self, error: str, last_sql: str, errors: list[str]) -> str:
        """Format a failed query as a JSON string.

        Args:
            error: The final error message.
            last_sql: The last SQL that was attempted.
            errors: Full list of errors accumulated during retry loop.

        Returns:
            JSON string with keys: error, attempted_sql, errors, suggestion.
        """
        result = {
            "error": error,
            "attempted_sql": last_sql,
            "errors": errors,
            "suggestion": (
                "Try rephrasing your question or call the `describe_schema` tool first."
            ),
        }
        return json.dumps(result, default=_json_default, indent=2)
