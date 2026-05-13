"""G16 acceptance tests for OpenTelemetry instrumentation.

The ``memory_span_exporter`` fixture (see ``tests/conftest.py``) installs an
in-memory exporter and replaces module-level cached tracers so spans land in
``exporter.get_finished_spans()`` for assertion.
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from src.core.schema_inspector import SchemaInspector
from src.core.self_corrector import SelfCorrector
from src.core.sql_executor import SQLExecutor
from src.core.sql_validator import SQLValidator


# ---------------------------------------------------------------------------
# Fixtures local to this file
# ---------------------------------------------------------------------------


@pytest.fixture
def engine():
    e = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with e.connect() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"))
        conn.execute(text("INSERT INTO users (name) VALUES ('Alice'), ('Bob')"))
        conn.commit()
    yield e
    e.dispose()


@pytest.fixture
def user_settings():
    s = MagicMock()
    s.max_self_correction_retries = 3
    s.max_llm_chars_per_request = 1_000_000
    s.max_query_rows = 100
    s.query_timeout_seconds = 10
    return s


def _spans_by_name(exporter):
    return {s.name: s for s in exporter.get_finished_spans()}


def _all_spans(exporter):
    return list(exporter.get_finished_spans())


# ---------------------------------------------------------------------------
# Schema inspector spans
# ---------------------------------------------------------------------------


def test_schema_cache_hit_attribute(engine, memory_span_exporter):
    inspector = SchemaInspector(engine)
    inspector.get_full_schema()
    inspector.get_full_schema()

    spans = [
        s for s in memory_span_exporter.get_finished_spans() if s.name == "schema.get_full_schema"
    ]
    assert len(spans) == 2
    # Order: SimpleSpanProcessor exports in call order
    assert spans[0].attributes["schema.cache_hit"] is False
    assert spans[0].attributes["schema.table_count"] == 1
    assert spans[1].attributes["schema.cache_hit"] is True


def test_schema_refresh_emits_span(engine, memory_span_exporter):
    inspector = SchemaInspector(engine)
    inspector.refresh()
    spans = _spans_by_name(memory_span_exporter)
    assert "schema.refresh" in spans
    assert spans["schema.refresh"].attributes["schema.refreshed"] is True


# ---------------------------------------------------------------------------
# Corrector + executor + validator span tree
# ---------------------------------------------------------------------------


async def test_span_tree_structure(engine, user_settings, memory_span_exporter):
    """Successful corrector run produces nested spans:
    corrector.execute_with_correction → corrector.attempt → (sql.validate, db.execute).
    """
    inspector = SchemaInspector(engine)
    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT id, name FROM users")
    validator = SQLValidator(inspector, max_query_rows=100)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        executor = SQLExecutor(engine, user_settings, pool)
        corrector = SelfCorrector(
            generator, validator, executor, user_settings, inspector=inspector
        )
        result = await corrector.execute_with_correction("list users", "sqlite")
        assert result["success"] is True
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    spans = _all_spans(memory_span_exporter)
    by_name = {s.name: s for s in spans}
    assert "corrector.execute_with_correction" in by_name
    assert "corrector.attempt" in by_name
    assert "sql.validate" in by_name
    assert "db.execute" in by_name

    parent = by_name["corrector.execute_with_correction"]
    attempt = by_name["corrector.attempt"]
    validate = by_name["sql.validate"]
    db_exec = by_name["db.execute"]

    assert attempt.parent.span_id == parent.context.span_id
    assert validate.parent.span_id == attempt.context.span_id
    assert db_exec.parent.span_id == attempt.context.span_id

    assert parent.attributes["corrector.max_retries"] == 3
    assert parent.attributes["corrector.final_attempts"] == 1
    assert parent.attributes["corrector.schema_refreshed"] is False
    assert validate.attributes["validation.passed"] is True


async def test_db_statement_hashed_by_default(engine, user_settings, memory_span_exporter):
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        executor = SQLExecutor(engine, user_settings, pool)
        rows = await executor.execute("SELECT id FROM users LIMIT 1")
        assert rows
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    span = _spans_by_name(memory_span_exporter)["db.execute"]
    assert span.attributes["db.system"] == "sqlite"
    assert len(span.attributes["db.statement.hash"]) == 16
    assert "db.statement" not in span.attributes
    assert span.attributes["db.rows_affected"] == 1


async def test_db_statement_text_when_opted_in(
    engine, user_settings, memory_span_exporter, monkeypatch
):
    monkeypatch.setattr("src.config.settings.otel_capture_sql_text", True)
    sql = "SELECT id FROM users LIMIT 1"
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        executor = SQLExecutor(engine, user_settings, pool)
        await executor.execute(sql)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    span = _spans_by_name(memory_span_exporter)["db.execute"]
    assert span.attributes.get("db.statement") == sql


# ---------------------------------------------------------------------------
# LLM span: provider + token usage
# ---------------------------------------------------------------------------


async def test_llm_span_carries_token_usage(memory_span_exporter, monkeypatch):
    """Patch the Anthropic client directly so we can verify token-usage attrs land on the llm.generate span."""
    import anthropic
    from src.config import UserSettings
    from src.core.sql_generator import SQLGenerator

    fake_text_block = MagicMock(spec=anthropic.types.TextBlock)
    fake_text_block.text = "SELECT 1"
    fake_response = MagicMock()
    fake_response.content = [fake_text_block]
    fake_response.usage = MagicMock(input_tokens=42, output_tokens=11)

    inspector = MagicMock()
    inspector.get_full_schema.return_value = ""
    settings = UserSettings(
        llm_provider="anthropic",
        anthropic_api_key="sk-test",
        groq_api_key="",
        claude_model="claude-sonnet-4-6",
        groq_model="llama",
        max_query_rows=100,
        query_timeout_seconds=10,
        max_self_correction_retries=3,
    )
    generator = SQLGenerator(settings, inspector)
    monkeypatch.setattr(generator._client.messages, "create", AsyncMock(return_value=fake_response))

    out = await generator.generate("anything")
    assert out == "SELECT 1"

    span = _spans_by_name(memory_span_exporter)["llm.generate"]
    assert span.attributes["gen_ai.system"] == "anthropic"
    assert span.attributes["gen_ai.request.model"] == "claude-sonnet-4-6"
    assert span.attributes["gen_ai.usage.input_tokens"] == 42
    assert span.attributes["gen_ai.usage.output_tokens"] == 11


# ---------------------------------------------------------------------------
# Schema-drift triggers refresh + retry — final_attempts >= 2
# ---------------------------------------------------------------------------


async def test_corrector_records_schema_refresh(engine, user_settings, memory_span_exporter):
    """Schema drift mid-session: parent span records schema_refreshed=True and final_attempts >= 2."""
    inspector = SchemaInspector(engine)
    inspector.get_full_schema()  # prime cache with pre-drop schema
    # Add a column out-of-band so the cached SELECT references something missing
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE users ADD COLUMN email TEXT"))
        conn.commit()

    generator = MagicMock()
    # First attempt references a column the LIVE DB has but the cache doesn't
    # know about — but we want the OPPOSITE: a query that fails because the
    # cache references something. Easier: generate a SELECT for "missing" then
    # repair to a working one.
    generator.generate = AsyncMock(return_value="SELECT not_a_column FROM users")
    generator.get_schema_context = MagicMock(side_effect=lambda: inspector.get_full_schema())
    generator.generate_from_prompt = AsyncMock(return_value="SELECT id FROM users LIMIT 5")

    validator = SQLValidator(inspector, max_query_rows=100)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        executor = SQLExecutor(engine, user_settings, pool)
        corrector = SelfCorrector(
            generator, validator, executor, user_settings, inspector=inspector
        )
        result = await corrector.execute_with_correction("list users", "sqlite")
        assert result["success"] is True
        assert result["attempts"] >= 2
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    by_name = _spans_by_name(memory_span_exporter)
    parent = by_name["corrector.execute_with_correction"]
    assert parent.attributes["corrector.schema_refreshed"] is True
    assert parent.attributes["corrector.final_attempts"] >= 2
    assert "schema.refresh" in by_name


# ---------------------------------------------------------------------------
# mcp.ask_database root span + request.id propagation
# ---------------------------------------------------------------------------


@pytest.fixture
def ask_database_harness(engine, user_settings, monkeypatch):
    """Wire src.server module globals so ask_database can run without the lifespan."""
    import src.server as server
    from src.auth.middleware import user_config_var
    from src.auth.user_store import UserConfig
    from src.core.pipeline_factory import PipelineComponents
    from src.core.result_formatter import ResultFormatter

    inspector = SchemaInspector(engine)
    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT id, name FROM users")
    validator = SQLValidator(inspector, max_query_rows=100)
    pool = ThreadPoolExecutor(max_workers=2)
    executor = SQLExecutor(engine, user_settings, pool)
    corrector = SelfCorrector(generator, validator, executor, user_settings, inspector=inspector)
    components = PipelineComponents(
        inspector=inspector,
        generator=generator,
        validator=validator,
        executor=executor,
        corrector=corrector,
        formatter=ResultFormatter(),
        dialect="sqlite",
        engine=engine,
    )
    factory = MagicMock()
    factory.get = AsyncMock(return_value=components)

    query_log = MagicMock()
    query_log.log_query = MagicMock()

    monkeypatch.setattr(server, "_factory", factory)
    monkeypatch.setattr(server, "_query_log", query_log)
    monkeypatch.setattr(server, "_user_store", None)
    monkeypatch.setattr(server, "_mcp_limiter", None)
    monkeypatch.setattr(server, "_drain_state", None)
    server._cache.clear()

    user_config = UserConfig(
        user_id="test-user",
        database_url="sqlite:///:memory:",
        is_active=True,
        onboarding_status="complete",
        email="t@example.com",
        api_key_id="key-1",
    )
    token = user_config_var.set(user_config)
    try:
        yield server
    finally:
        user_config_var.reset(token)
        pool.shutdown(wait=False, cancel_futures=True)


async def test_ask_database_emits_root_span(ask_database_harness, memory_span_exporter):
    server = ask_database_harness
    result = await server.ask_database("list users")
    assert "data" in result or "row_count" in result or "Alice" in result

    by_name = _spans_by_name(memory_span_exporter)
    root = by_name["mcp.ask_database"]
    assert root.attributes["mcp.tool.name"] == "ask_database"
    assert root.attributes["mcp.user_id"] == "test-user"
    assert root.attributes["mcp.attempts"] == 1
    assert root.attributes["mcp.row_count"] == 2

    # The corrector span must be a child of the root span.
    corrector_span = by_name["corrector.execute_with_correction"]
    assert corrector_span.parent.span_id == root.context.span_id


async def test_request_id_on_root_span(ask_database_harness, memory_span_exporter):
    from src.middleware.request_id import request_id_var

    token = request_id_var.set("req-abc-123")
    try:
        await ask_database_harness.ask_database("list users")
    finally:
        request_id_var.reset(token)

    root = _spans_by_name(memory_span_exporter)["mcp.ask_database"]
    assert root.attributes["request.id"] == "req-abc-123"
