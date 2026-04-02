"""MCP tool: describe a single table's columns, keys, and sample values."""

import json

from src.core.schema_inspector import SchemaInspector


def describe_schema(table_name: str, inspector: SchemaInspector) -> str:
    """Return detailed schema info for *table_name* as a string.

    Returns a JSON error object if the table does not exist so the MCP
    client always receives a well-formed response.
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
    return inspector.get_table_detail(table_name)
