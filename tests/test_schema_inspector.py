"""Unit tests for SchemaInspector using an in-memory SQLite database."""

import pytest
from sqlalchemy import Column, ForeignKey, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session

from src.core.schema_inspector import SchemaInspector


# ---------------------------------------------------------------------------
# In-memory schema: authors → books (FK relationship)
# ---------------------------------------------------------------------------


class _Base(DeclarativeBase):
    pass


class _Author(_Base):
    __tablename__ = "authors"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)


class _Book(_Base):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True)
    title = Column(String, nullable=False)
    author_id = Column(Integer, ForeignKey("authors.id"), nullable=False)


@pytest.fixture(scope="module")
def engine():
    e = create_engine("sqlite:///:memory:")
    _Base.metadata.create_all(e)
    with Session(e) as session:
        a1 = _Author(id=1, name="Alice")
        a2 = _Author(id=2, name="Bob")
        session.add_all([a1, a2])
        session.flush()
        session.add_all([
            _Book(title="Python Tricks", author_id=1),
            _Book(title="Clean Code", author_id=2),
        ])
        session.commit()
    return e


@pytest.fixture(scope="module")
def inspector(engine):
    return SchemaInspector(engine)


# ---------------------------------------------------------------------------
# get_table_names
# ---------------------------------------------------------------------------


def test_get_table_names_returns_all_tables(inspector):
    names = inspector.get_table_names()
    assert set(names) == {"authors", "books"}


def test_get_table_names_returns_list(inspector):
    assert isinstance(inspector.get_table_names(), list)


# ---------------------------------------------------------------------------
# get_columns
# ---------------------------------------------------------------------------


def test_get_columns_returns_correct_names_for_authors(inspector):
    cols = [c["name"] for c in inspector.get_columns("authors")]
    assert "id" in cols
    assert "name" in cols


def test_get_columns_id_is_integer_type(inspector):
    cols = {c["name"]: c for c in inspector.get_columns("authors")}
    type_str = str(cols["id"]["type"]).upper()
    assert "INT" in type_str


def test_get_columns_name_is_string_type(inspector):
    cols = {c["name"]: c for c in inspector.get_columns("authors")}
    type_str = str(cols["name"]["type"]).upper()
    assert "VARCHAR" in type_str or "TEXT" in type_str or "STRING" in type_str


def test_get_columns_books_includes_fk_column(inspector):
    cols = [c["name"] for c in inspector.get_columns("books")]
    assert "author_id" in cols
    assert "title" in cols


# ---------------------------------------------------------------------------
# get_foreign_keys
# ---------------------------------------------------------------------------


def test_get_foreign_keys_books_has_one_fk(inspector):
    fks = inspector.get_foreign_keys("books")
    assert len(fks) == 1


def test_get_foreign_keys_books_refers_to_authors(inspector):
    fk = inspector.get_foreign_keys("books")[0]
    assert fk["referred_table"] == "authors"


def test_get_foreign_keys_books_constrained_column_is_author_id(inspector):
    fk = inspector.get_foreign_keys("books")[0]
    assert "author_id" in fk["constrained_columns"]


def test_get_foreign_keys_books_referred_column_is_id(inspector):
    fk = inspector.get_foreign_keys("books")[0]
    assert "id" in fk["referred_columns"]


def test_get_foreign_keys_authors_has_none(inspector):
    assert inspector.get_foreign_keys("authors") == []


# ---------------------------------------------------------------------------
# get_full_schema
# ---------------------------------------------------------------------------


def test_get_full_schema_is_nonempty_string(inspector):
    schema = inspector.get_full_schema()
    assert isinstance(schema, str)
    assert len(schema) > 0


def test_get_full_schema_contains_all_table_names(inspector):
    schema = inspector.get_full_schema()
    assert "authors" in schema
    assert "books" in schema


def test_get_full_schema_contains_column_names(inspector):
    schema = inspector.get_full_schema()
    assert "id" in schema
    assert "name" in schema
    assert "title" in schema


def test_get_full_schema_contains_fk_notation(inspector):
    schema = inspector.get_full_schema()
    assert "FK:" in schema


# ---------------------------------------------------------------------------
# get_sample_values
# ---------------------------------------------------------------------------


def test_get_sample_values_returns_list(inspector):
    values = inspector.get_sample_values("authors", "name")
    assert isinstance(values, list)


def test_get_sample_values_returns_actual_data(inspector):
    values = inspector.get_sample_values("authors", "name")
    assert "Alice" in values or "Bob" in values


def test_get_sample_values_respects_limit(inspector):
    values = inspector.get_sample_values("authors", "name", limit=1)
    assert len(values) <= 1


def test_get_sample_values_for_integer_column(inspector):
    values = inspector.get_sample_values("authors", "id")
    assert isinstance(values, list)
    assert len(values) > 0
    assert all(isinstance(v, int) for v in values)
