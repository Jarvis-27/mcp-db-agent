"""MCP resource: expose the full database schema as a readable context endpoint."""

from src.core.schema_inspector import SchemaInspector


def get_schema_overview(inspector: SchemaInspector) -> str:
    """Return the complete database schema in compact DDL-like notation.

    Registered at URI ``schema://overview``. MCP clients can fetch this
    resource to inject the schema into their context before querying, which
    improves SQL generation accuracy without needing a round-trip through
    ``describe_schema``.
    """
    return inspector.get_full_schema()
