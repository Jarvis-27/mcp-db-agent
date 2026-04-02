"""MCP tool: list all tables in the database with their row counts."""

import json

from src.core.schema_inspector import SchemaInspector


def list_tables(inspector: SchemaInspector) -> str:
    """Return every table name and its row count as a JSON string."""
    tables = inspector.get_tables_with_counts()
    return json.dumps(tables, indent=2)
