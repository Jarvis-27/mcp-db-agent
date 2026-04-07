"""Tests for SQLGenerator: mock-based unit tests + real-API integration tests."""

import pytest
from sqlalchemy import create_engine
from unittest.mock import AsyncMock, MagicMock

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
# Mock-based unit tests for generate() — no API call
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_inspector():
    insp = MagicMock()
    insp.get_full_schema.return_value = "TABLE: users\n  id INTEGER PRIMARY KEY\n  name VARCHAR"
    insp.get_table_names.return_value = ["users"]
    return insp


def _patch_client(gen: SQLGenerator, raw_sql: str) -> None:
    """Replace the LLM client on *gen* so it returns *raw_sql* verbatim.

    Mocking at the client level (rather than _call_llm) ensures _clean_sql
    still runs, which is the behaviour we want to verify.
    """
    import groq as _groq

    if isinstance(gen._client, _groq.AsyncGroq):
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = raw_sql
        gen._client = MagicMock(spec=_groq.AsyncGroq)
        gen._client.chat.completions.create = AsyncMock(return_value=mock_resp)
    else:
        import anthropic as _ant

        block = MagicMock(spec=_ant.types.TextBlock)
        block.text = raw_sql
        mock_resp = MagicMock()
        mock_resp.content = [block]
        gen._client = MagicMock(spec=_ant.AsyncAnthropic)
        gen._client.messages.create = AsyncMock(return_value=mock_resp)


async def test_generate_calls_llm_with_schema_in_prompt(mock_inspector):
    """generate() must embed the schema string in the prompt sent to the LLM."""
    gen = SQLGenerator(settings, mock_inspector)
    gen._call_llm = AsyncMock(return_value="SELECT COUNT(*) FROM users u")

    await gen.generate("How many users are there?", "sqlite")

    prompt = gen._call_llm.call_args[0][0]
    assert "TABLE: users" in prompt
    assert "How many users are there?" in prompt


async def test_generate_includes_dialect_in_prompt(mock_inspector):
    """generate() must mention the target dialect in the LLM prompt."""
    gen = SQLGenerator(settings, mock_inspector)
    gen._call_llm = AsyncMock(return_value="SELECT 1")

    await gen.generate("Any question", "postgresql")

    prompt = gen._call_llm.call_args[0][0]
    assert "postgresql" in prompt.lower()


async def test_generate_strips_markdown_fence_from_response(mock_inspector):
    """generate() must strip ```sql ... ``` fences returned by the LLM."""
    gen = SQLGenerator(settings, mock_inspector)
    _patch_client(gen, "```sql\nSELECT id FROM users u\n```")

    sql = await gen.generate("List user IDs", "sqlite")

    assert "```" not in sql
    assert sql == "SELECT id FROM users u"


async def test_generate_strips_plain_fence_from_response(mock_inspector):
    """generate() must strip plain ``` fences too, not just ```sql."""
    gen = SQLGenerator(settings, mock_inspector)
    _patch_client(gen, "```\nSELECT 1\n```")

    sql = await gen.generate("Simple query", "sqlite")

    assert sql == "SELECT 1"


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
