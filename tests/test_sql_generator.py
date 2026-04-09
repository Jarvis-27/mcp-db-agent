"""Tests for SQLGenerator: mock-based unit tests + real-API integration tests.

Unit tests use mock_inspector and never hit a database or LLM API.
Integration tests (marked @pytest.mark.integration) require a real LLM API
key in .env but use a self-contained in-memory SQLite database — they do NOT
depend on DATABASE_URL or demo.db.

Run unit tests:        uv run pytest tests/test_sql_generator.py -m "not integration" -v
Run integration tests: uv run pytest tests/test_sql_generator.py -m integration -v
"""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool
from unittest.mock import AsyncMock, MagicMock

from src.config import settings
from src.core.schema_inspector import SchemaInspector
from src.core.sql_generator import SQLGenerator, _clean_sql


# ---------------------------------------------------------------------------
# Self-contained demo schema for integration tests
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _User(_Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String)


class _Product(_Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True)
    name = Column(String)
    price = Column(Integer)
    category = Column(String)


class _Order(_Base):
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    status = Column(String)


class _OrderItem(_Base):
    __tablename__ = "order_items"

    id = Column(Integer, primary_key=True)
    order_id = Column(Integer, ForeignKey("orders.id"))
    product_id = Column(Integer, ForeignKey("products.id"))
    quantity = Column(Integer)
    price = Column(Integer)


@pytest.fixture(scope="module")
def engine():
    """Shared in-memory SQLite engine with demo-like schema.

    StaticPool keeps a single underlying connection so that all SQLAlchemy
    sessions — including thread-pool ones — see the same data.
    Not reliant on DATABASE_URL or any external resource.
    """
    e = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _Base.metadata.create_all(e)
    with Session(e) as session:
        session.add_all(
            [
                _User(id=1, name="Alice", email="alice@example.com"),
                _User(id=2, name="Bob", email="bob@example.com"),
                _User(id=3, name="Carol", email="carol@example.com"),
            ]
        )
        session.flush()
        session.add_all(
            [
                _Product(id=1, name="Widget", price=1000, category="tools"),
                _Product(id=2, name="Gadget", price=2000, category="electronics"),
            ]
        )
        session.flush()
        session.add_all(
            [
                _Order(id=1, user_id=1, status="shipped"),
                _Order(id=2, user_id=2, status="pending"),
                _Order(id=3, user_id=3, status="delivered"),
            ]
        )
        session.flush()
        session.add_all(
            [
                _OrderItem(id=1, order_id=1, product_id=1, quantity=2, price=2000),
                _OrderItem(id=2, order_id=2, product_id=2, quantity=1, price=2000),
            ]
        )
        session.commit()
    return e


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
# Schema prompt test — no LLM call, but uses real schema inspection
# ---------------------------------------------------------------------------


def test_prompt_includes_schema(inspector):
    """Verify _build_prompt embeds the real schema string."""
    gen = SQLGenerator(settings, inspector)
    prompt = gen._build_prompt("test question", "sqlite")
    schema = inspector.get_full_schema()
    assert schema in prompt
    assert "sqlite" in prompt.lower()
    assert "test question" in prompt


# ---------------------------------------------------------------------------
# Real API integration tests — require LLM API key in .env
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_generate_returns_string(generator):
    sql = await generator.generate("How many users are there?")
    assert isinstance(sql, str)
    assert len(sql) > 0


@pytest.mark.integration
async def test_generate_no_markdown_fences(generator):
    sql = await generator.generate("List all product categories")
    assert "```" not in sql


@pytest.mark.integration
async def test_generate_select_only(generator):
    sql = await generator.generate("Show the top 5 products by price")
    assert sql.strip().upper().startswith("SELECT")


@pytest.mark.integration
async def test_generate_references_existing_table(generator, inspector):
    sql = await generator.generate("Show me 3 orders with their status")
    table_names = inspector.get_table_names()
    assert any(t in sql.lower() for t in table_names)


@pytest.mark.integration
async def test_generate_aggregation_query(generator):
    sql = await generator.generate("What is the total revenue from all orders?")
    upper = sql.upper()
    assert any(kw in upper for kw in ("SUM", "COUNT", "AVG", "MAX", "MIN", "TOTAL"))


@pytest.mark.integration
async def test_generate_join_query(generator):
    sql = await generator.generate("Show me orders along with the user's name who placed them")
    upper = sql.upper()
    assert "JOIN" in upper


@pytest.mark.integration
async def test_generate_sqlite_dialect(generator):
    sql = await generator.generate("Show orders placed in 2024", dialect="sqlite")
    assert isinstance(sql, str)
    assert len(sql) > 0
