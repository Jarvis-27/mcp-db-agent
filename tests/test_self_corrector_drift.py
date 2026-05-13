"""G9 acceptance: schema drift between requests triggers refresh + repair.

Uses a real SQLite engine, real SchemaInspector, real SQLExecutor, real
SQLValidator — only the LLM-facing SQLGenerator is mocked, so the test runs
in CI without an API key while still exercising the full cache-bust +
introspection flow against a live driver.
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


@pytest.fixture
def engine():
    e = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with e.connect() as conn:
        conn.execute(
            text("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)")
        )
        conn.execute(text("INSERT INTO users (name, email) VALUES ('Alice', 'a@x.com')"))
        conn.commit()
    yield e
    e.dispose()


@pytest.fixture
def settings():
    s = MagicMock()
    s.max_self_correction_retries = 3
    s.max_llm_chars_per_request = 1_000_000
    s.max_query_rows = 100
    s.query_timeout_seconds = 10
    return s


async def test_drift_mid_session_triggers_refresh_and_succeeds(engine, settings):
    inspector = SchemaInspector(engine)
    primed = inspector.get_full_schema()
    assert "email" in primed  # cache primed with pre-drop schema

    # Drop the column out-of-band — the cache is now stale.  SQLite 3.35+
    # supports ALTER TABLE ... DROP COLUMN natively; the dev/CI Python ships
    # with 3.45+ so no fallback is needed.
    with engine.connect() as conn:
        conn.execute(text("ALTER TABLE users DROP COLUMN email"))
        conn.commit()

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT email FROM users")
    generator.get_schema_context = MagicMock(side_effect=lambda: inspector.get_full_schema())
    generator.generate_from_prompt = AsyncMock(return_value="SELECT id FROM users LIMIT 10")

    validator = SQLValidator(inspector, max_query_rows=100)
    pool = ThreadPoolExecutor(max_workers=2)
    try:
        executor = SQLExecutor(engine, settings, pool)
        corrector = SelfCorrector(
            generator, validator, executor, settings, inspector=inspector
        )
        result = await corrector.execute_with_correction("list user ids", "sqlite")

        assert result["success"] is True
        assert result["attempts"] >= 2
        # The repair prompt's *schema section* must reflect the post-drop
        # schema — the rest of the prompt naturally mentions 'email' via the
        # failed SQL and error message, which is fine.  We isolate the
        # schema block between the "Database schema:" and "Failed SQL:"
        # markers used by SelfCorrector._fix_sql.
        repair_prompt = generator.generate_from_prompt.call_args[0][0]
        schema_block = repair_prompt.split("Database schema:", 1)[1].split("Failed SQL:", 1)[0]
        assert "email" not in schema_block, (
            f"Schema in repair prompt still references dropped column: {schema_block!r}"
        )
        # And the inspector cache reflects the post-drop truth on its own.
        assert "email" not in inspector.get_full_schema()
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
