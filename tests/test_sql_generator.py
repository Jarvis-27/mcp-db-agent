"""Integration tests for SQLGenerator using the real LLM API and demo.db."""

import pytest
from sqlalchemy import create_engine

from src.config import settings
from src.core.schema_inspector import SchemaInspector
from src.core.sql_generator import SQLGenerator, _clean_sql


@pytest.fixture(scope="module")
def engine():
    return create_engine(settings.database_url)


@pytest.fixture(scope="module")
def inspector(engine):
    return SchemaInspector(engine)


@pytest.fixture(scope="module")
def generator(inspector):
    return SQLGenerator(settings, inspector)


# ---------------------------------------------------------------------------
# _clean_sql unit tests (no API call)
# ---------------------------------------------------------------------------

def test_clean_sql_strips_sql_fence():
    assert _clean_sql("```sql\nSELECT 1\n```") == "SELECT 1"


def test_clean_sql_strips_plain_fence():
    assert _clean_sql("```\nSELECT 1\n```") == "SELECT 1"


def test_clean_sql_strips_whitespace():
    assert _clean_sql("  SELECT 1  ") == "SELECT 1"


def test_clean_sql_passthrough():
    assert _clean_sql("SELECT * FROM users u LIMIT 5") == "SELECT * FROM users u LIMIT 5"


# ---------------------------------------------------------------------------
# Real API integration tests
# ---------------------------------------------------------------------------

async def test_generate_returns_string(generator):
    sql = await generator.generate("How many users are there?")
    assert isinstance(sql, str)
    assert len(sql) > 0


async def test_generate_no_markdown_fences(generator):
    sql = await generator.generate("List all product categories")
    assert "```" not in sql


async def test_generate_select_only(generator):
    sql = await generator.generate("Show the top 5 products by price")
    assert sql.strip().upper().startswith("SELECT")


async def test_generate_references_existing_table(generator, inspector):
    sql = await generator.generate("Show me 3 orders with their status")
    table_names = inspector.get_table_names()
    assert any(t in sql.lower() for t in table_names)


async def test_generate_aggregation_query(generator):
    sql = await generator.generate("What is the total revenue from all orders?")
    upper = sql.upper()
    assert any(kw in upper for kw in ("SUM", "COUNT", "AVG", "MAX", "MIN", "TOTAL"))


async def test_generate_join_query(generator):
    sql = await generator.generate("Show me orders along with the user's name who placed them")
    upper = sql.upper()
    assert "JOIN" in upper


async def test_generate_sqlite_dialect(generator):
    sql = await generator.generate("Show orders placed in 2024", dialect="sqlite")
    assert isinstance(sql, str)
    assert len(sql) > 0


async def test_prompt_includes_schema(inspector):
    """Verify _build_prompt embeds the real schema string."""
    gen = SQLGenerator(settings, inspector)
    prompt = gen._build_prompt("test question", "sqlite")
    schema = inspector.get_full_schema()
    # Schema content should appear verbatim in the prompt
    assert schema in prompt
    assert "sqlite" in prompt.lower()
    assert "test question" in prompt
