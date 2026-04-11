"""Tests for SchemaInspector TTL cache and refresh()."""

from unittest.mock import MagicMock, patch

import pytest

from src.core.schema_inspector import SchemaInspector


@pytest.fixture
def mock_engine():
    engine = MagicMock()
    engine.dialect.name = "sqlite"
    return engine


def _make_inspector(engine, ttl=600):
    with patch("src.core.schema_inspector.inspect") as mock_inspect:
        mock_inspector = MagicMock()
        mock_inspector.get_table_names.return_value = ["users"]
        mock_inspector.get_columns.return_value = [
            {"name": "id", "type": MagicMock(__str__=lambda s: "INTEGER"), "nullable": False}
        ]
        mock_inspector.get_pk_constraint.return_value = {"constrained_columns": ["id"]}
        mock_inspector.get_foreign_keys.return_value = []
        mock_inspect.return_value = mock_inspector
        inspector = SchemaInspector(engine, cache_ttl_seconds=ttl)
        inspector._inspector = mock_inspector
    return inspector, mock_inspector


def test_first_call_builds_schema(mock_engine):
    inspector, mock_inspector = _make_inspector(mock_engine)
    schema = inspector.get_full_schema()
    assert "users" in schema
    assert mock_inspector.get_table_names.call_count == 1


def test_second_call_within_ttl_uses_cache(mock_engine):
    inspector, mock_inspector = _make_inspector(mock_engine)
    schema1 = inspector.get_full_schema()
    schema2 = inspector.get_full_schema()
    assert schema1 == schema2
    # get_table_names should only be called once — second call hits cache
    assert mock_inspector.get_table_names.call_count == 1


def test_cache_expires_after_ttl(mock_engine):
    inspector, mock_inspector = _make_inspector(mock_engine, ttl=1)
    inspector.get_full_schema()

    # Manually expire the cache timestamp
    cached_text, _ = inspector._schema_cache
    inspector._schema_cache = (cached_text, 0.0)  # Force TTL expiry

    inspector.get_full_schema()
    assert mock_inspector.get_table_names.call_count == 2


def test_refresh_busts_cache(mock_engine):
    inspector, mock_inspector = _make_inspector(mock_engine)
    inspector.get_full_schema()
    assert inspector._schema_cache is not None

    with patch("src.core.schema_inspector.inspect", return_value=mock_inspector):
        inspector.refresh()

    assert inspector._schema_cache is None
    inspector.get_full_schema()
    assert mock_inspector.get_table_names.call_count == 2


def test_refresh_reinitialises_sqlalchemy_inspector(mock_engine):
    inspector, _ = _make_inspector(mock_engine)
    old_inspector = inspector._inspector

    new_mock = MagicMock()
    new_mock.get_table_names.return_value = ["products"]
    new_mock.get_columns.return_value = []
    new_mock.get_pk_constraint.return_value = {"constrained_columns": []}
    new_mock.get_foreign_keys.return_value = []

    with patch("src.core.schema_inspector.inspect", return_value=new_mock):
        inspector.refresh()

    assert inspector._inspector is not old_inspector
