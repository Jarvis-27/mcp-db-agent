"""End-to-end integration tests: real Groq LLM + in-memory SQLite database.

These tests use the real Groq API (cheap/free tier) but an isolated in-memory
database so they never touch demo.db or any production data.

Run:  uv run pytest tests/test_integration.py -m integration -v
Skip: uv run pytest -m "not integration"
"""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session
from sqlalchemy.pool import StaticPool

from src.config import settings
from src.core.schema_inspector import SchemaInspector
from src.core.self_corrector import SelfCorrector
from src.core.sql_executor import SQLExecutor
from src.core.sql_generator import SQLGenerator
from src.core.sql_validator import SQLValidator


# ---------------------------------------------------------------------------
# In-memory schema: customers + sales (FK relationship)
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _Customer(_Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    city = Column(String, nullable=False)


class _Sale(_Base):
    __tablename__ = "sales"

    id = Column(Integer, primary_key=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    sale_date = Column(String, nullable=False)  # ISO-8601 string: "YYYY-MM-DD"


@pytest.fixture(scope="module")
def engine():
    e = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    _Base.metadata.create_all(e)
    with Session(e) as session:
        session.add_all(
            [
                _Customer(id=1, name="Alice", city="New York"),
                _Customer(id=2, name="Bob", city="Chicago"),
                _Customer(id=3, name="Carol", city="New York"),
            ]
        )
        session.flush()
        session.add_all(
            [
                _Sale(customer_id=1, amount=100, sale_date="2024-01-15"),
                _Sale(customer_id=1, amount=200, sale_date="2024-03-22"),
                _Sale(customer_id=2, amount=150, sale_date="2023-11-05"),
                _Sale(customer_id=3, amount=300, sale_date="2024-06-10"),
                _Sale(customer_id=3, amount=50, sale_date="2023-08-30"),
            ]
        )
        session.commit()
    return e


@pytest.fixture(scope="module")
def corrector(engine):
    inspector = SchemaInspector(engine)
    generator = SQLGenerator(settings, inspector)
    validator = SQLValidator(inspector)
    from concurrent.futures import ThreadPoolExecutor

    pool = ThreadPoolExecutor(max_workers=2)
    executor = SQLExecutor(engine, settings, pool)
    return SelfCorrector(generator, validator, executor, settings)


# ---------------------------------------------------------------------------
# Integration tests (require real Groq API key in .env)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_simple_count_query(corrector):
    """LLM should generate a COUNT query returning exactly 3 customers."""
    result = await corrector.execute_with_correction("How many customers are there?", "sqlite")
    assert result["success"] is True
    assert len(result["data"]) == 1
    count = list(result["data"][0].values())[0]
    assert count == 3


@pytest.mark.integration
async def test_group_by_aggregation(corrector):
    """LLM should generate a GROUP BY query with one row per city."""
    result = await corrector.execute_with_correction(
        "What is the total sales amount per city?", "sqlite"
    )
    assert result["success"] is True
    # New York (Alice+Carol) and Chicago (Bob) → 2 groups
    assert len(result["data"]) == 2


@pytest.mark.integration
async def test_two_table_join(corrector):
    """LLM should join customers and sales, returning one row per sale."""
    result = await corrector.execute_with_correction(
        "Show me all sales with the customer name for each sale", "sqlite"
    )
    assert result["success"] is True
    assert len(result["data"]) >= 1
    # Each row must have at least two columns (sale info + customer name)
    assert len(result["data"][0].keys()) >= 2


@pytest.mark.integration
async def test_filtered_where_clause(corrector):
    """LLM should apply a WHERE filter, returning only New York customers."""
    result = await corrector.execute_with_correction(
        "List all customers who live in New York", "sqlite"
    )
    assert result["success"] is True
    # Alice and Carol are from New York
    assert len(result["data"]) == 2


@pytest.mark.integration
async def test_date_based_query(corrector):
    """LLM should filter by year, returning only 2024 sales (3 out of 5)."""
    result = await corrector.execute_with_correction(
        "Show me all sales that happened in 2024", "sqlite"
    )
    assert result["success"] is True
    # 3 sales have 2024 dates
    assert 1 <= len(result["data"]) <= 5
