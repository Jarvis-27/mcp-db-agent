"""MCP tool: fetch sample rows from a table for data exploration."""

import json

from src.core.result_formatter import _json_default
from src.core.schema_inspector import SchemaInspector


def get_sample_data(table_name: str, inspector: SchemaInspector, limit: int = 5) -> str:
    """Return up to *limit* rows from *table_name* as a JSON string.

    *limit* is clamped to [1, 20] — large samples belong in ask_database.
    Returns a JSON error object if the table does not exist.
    """
    if table_name not in inspector.get_table_names():
        return json.dumps(
            {
                "error": (
                    f"Table '{table_name}' not found. "
                    "Call list_tables to see available tables."
                )
            }
        )

    limit = max(1, min(limit, 20))
    rows = inspector.get_sample_rows(table_name, limit)
    return json.dumps(rows, indent=2, default=_json_default)
