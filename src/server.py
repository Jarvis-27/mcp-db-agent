"""MCP server entrypoint — wires all pipeline components and registers tools/resources."""

from mcp.server.fastmcp import FastMCP
from sqlalchemy import create_engine

from src.config import settings
from src.core.result_formatter import ResultFormatter
from src.core.schema_inspector import SchemaInspector
from src.core.self_corrector import SelfCorrector
from src.core.sql_executor import SQLExecutor
from src.core.sql_generator import SQLGenerator
from src.core.sql_validator import SQLValidator
from src.resources.schema_overview import get_schema_overview

# Import tool implementations under private aliases so the public names below
# can be used as the MCP-visible tool names without shadowing the imports.
from src.tools.ask_database import ask_database as _ask_database
from src.tools.describe_schema import describe_schema as _describe_schema
from src.tools.get_sample_data import get_sample_data as _get_sample_data
from src.tools.list_tables import list_tables as _list_tables

# ---------------------------------------------------------------------------
# Bootstrap — engine and pipeline components (shared across all requests)
# ---------------------------------------------------------------------------

engine = create_engine(settings.database_url)

inspector = SchemaInspector(engine)
generator = SQLGenerator(settings, inspector)
validator = SQLValidator(inspector)
executor = SQLExecutor(engine, settings)
corrector = SelfCorrector(generator, validator, executor, settings)
formatter = ResultFormatter()

# Derive the SQL dialect once at startup so every ask_database call uses the
# right date functions and syntax for the configured database.
dialect: str = "postgresql" if settings.database_url.startswith("postgresql") else "sqlite"

# ---------------------------------------------------------------------------
# MCP server instance
# ---------------------------------------------------------------------------

mcp = FastMCP("Database Analytics Agent")

# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


@mcp.resource("schema://overview")
def schema_overview() -> str:
    """Full database schema in compact DDL-like notation.

    Fetch this resource to inject the complete table and column definitions
    into your context before writing a query. It covers every table, column
    type, primary key, and foreign key relationship — equivalent to calling
    describe_schema on every table at once but faster.
    """
    return get_schema_overview(inspector)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def list_tables() -> str:
    """List all tables in the database with their row counts.

    Returns a JSON array where each element has ``table_name`` (str) and
    ``row_count`` (int). Call this first to discover what data is available
    before running a query or describing a specific table.
    """
    return _list_tables(inspector)


@mcp.tool()
def describe_schema(table_name: str) -> str:
    """Describe the columns, primary keys, foreign keys, and sample values for a table.

    Returns a formatted string with full column metadata — type, nullability,
    whether it is a primary key — plus a few sampled values per column so you
    can see what the data actually looks like before writing a query.

    Call list_tables first if you are unsure which tables exist.

    Args:
        table_name: Name of the table to describe.
    """
    return _describe_schema(table_name, inspector)


@mcp.tool()
def get_sample_data(table_name: str, limit: int = 5) -> str:
    """Get sample rows from a table to understand the data format and values.

    Returns a JSON array of row objects. The limit is clamped to [1, 20];
    use ask_database for larger result sets.

    Call list_tables first if you are unsure which tables exist.

    Args:
        table_name: Name of the table to sample.
        limit: Number of rows to return (1–20). Defaults to 5.
    """
    return _get_sample_data(table_name, inspector, limit)


@mcp.tool()
async def ask_database(question: str) -> str:
    """Ask a natural-language question about the database.

    The agent translates your question into SQL, validates it for safety
    (no writes allowed), executes it, and returns structured JSON results.
    If the generated SQL fails, it automatically retries with LLM-assisted
    self-correction up to three times before reporting failure.

    Returns a JSON object with:
    - ``query``: the SQL that was executed
    - ``row_count``: total number of rows returned
    - ``columns``: list of column names
    - ``data``: list of row dicts (capped at 100)
    - ``attempts``: number of generation/correction cycles used

    On failure:
    - ``error``: final error message
    - ``attempted_sql``: last SQL that was tried
    - ``errors``: full list of errors from each retry
    - ``suggestion``: hint for how to proceed

    Args:
        question: Plain-English question about the data, e.g.
                  "How many orders were placed in 2024?" or
                  "List the top 5 products by revenue."
    """
    return await _ask_database(question, corrector, formatter, dialect)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run(transport="stdio")
