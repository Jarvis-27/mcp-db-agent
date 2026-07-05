"""Unit tests for SelfCorrector — all LLM/DB calls are mocked."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.core.self_corrector import SelfCorrector, _is_llm_repairable
from src.core.sql_validator import ValidationResult


def _make_settings(max_retries: int = 3, max_chars: int = 1_000_000) -> MagicMock:
    s = MagicMock()
    s.max_self_correction_retries = max_retries
    # Plain int so chars-consumed comparisons work; default is effectively infinite
    # to keep pre-G6 tests unaffected.
    s.max_llm_chars_per_request = max_chars
    return s


@pytest.fixture(autouse=True)
def _no_backoff_sleep():
    """Skip the jittered backoff sleeps so tests run instantly."""
    with patch("src.core.self_corrector.asyncio.sleep", new=AsyncMock()):
        yield


def _make_corrector(
    generate_side_effect=None,
    generate_return="SELECT 1",
    generate_from_prompt_return="SELECT 1 FIXED",
    validate_return=None,
    execute_return=None,
    execute_side_effect=None,
    max_retries=3,
) -> SelfCorrector:
    generator = MagicMock()
    generator.generate = AsyncMock(
        side_effect=generate_side_effect,
        return_value=generate_return,
    )
    generator.generate_from_prompt = AsyncMock(return_value=generate_from_prompt_return)

    validator = MagicMock()
    validator.validate = MagicMock(return_value=validate_return or ValidationResult(is_valid=True))

    executor = MagicMock()
    executor.execute = AsyncMock(
        side_effect=execute_side_effect,
        return_value=execute_return or [],
    )

    return SelfCorrector(generator, validator, executor, _make_settings(max_retries))


# ---------------------------------------------------------------------------
# Happy-path: first attempt succeeds
# ---------------------------------------------------------------------------


async def test_success_on_first_attempt():
    rows = [{"id": 1, "name": "Alice"}]
    corrector = _make_corrector(
        generate_return="SELECT id, name FROM users LIMIT 5;",
        validate_return=ValidationResult(is_valid=True),
        execute_return=rows,
    )
    result = await corrector.execute_with_correction("List users", "sqlite")

    assert result["success"] is True
    assert result["data"] == rows
    assert result["attempts"] == 1
    assert result["errors"] == []


# ---------------------------------------------------------------------------
# Validator auto-injects LIMIT via modified_sql
# ---------------------------------------------------------------------------


async def test_limit_injection_used():
    original_sql = "SELECT * FROM users"
    modified_sql = "SELECT * FROM users LIMIT 100;"
    rows = [{"id": 1}]

    corrector = _make_corrector(
        generate_return=original_sql,
        validate_return=ValidationResult(
            is_valid=True, warning="No LIMIT added", modified_sql=modified_sql
        ),
        execute_return=rows,
    )
    result = await corrector.execute_with_correction("All users", "sqlite")

    assert result["success"] is True
    assert result["sql"] == modified_sql
    corrector._executor.execute.assert_awaited_once_with(modified_sql)


# ---------------------------------------------------------------------------
# Validation failure → self-correction → success
# ---------------------------------------------------------------------------


async def test_corrects_after_validation_failure():
    fixed_sql = "SELECT id FROM users LIMIT 10;"
    rows = [{"id": 1}]

    validator = MagicMock()
    validator.validate = MagicMock(
        side_effect=[
            ValidationResult(is_valid=False, error="Write operations are not allowed"),
            ValidationResult(is_valid=True),
        ]
    )

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="DELETE FROM users")
    generator.generate_from_prompt = AsyncMock(return_value=fixed_sql)

    executor = MagicMock()
    executor.execute = AsyncMock(return_value=rows)

    corrector = SelfCorrector(generator, validator, executor, _make_settings(3))
    result = await corrector.execute_with_correction("Delete users", "sqlite")

    assert result["success"] is True
    assert result["sql"] == fixed_sql
    assert result["attempts"] == 2
    assert len(result["errors"]) == 1
    generator.generate_from_prompt.assert_awaited_once()


# ---------------------------------------------------------------------------
# Execution failure → self-correction → success
# ---------------------------------------------------------------------------


async def test_corrects_after_execution_error():
    bad_sql = "SELECT * FROM nonexistent"
    good_sql = "SELECT id FROM users LIMIT 10;"
    rows = [{"id": 42}]

    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value=bad_sql)
    generator.generate_from_prompt = AsyncMock(return_value=good_sql)

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=[RuntimeError("no such table: nonexistent"), rows])

    corrector = SelfCorrector(generator, validator, executor, _make_settings(3))
    result = await corrector.execute_with_correction("Query nonexistent", "sqlite")

    assert result["success"] is True
    assert result["data"] == rows
    assert result["attempts"] == 2
    assert "no such table: nonexistent" in result["errors"]


# ---------------------------------------------------------------------------
# All retries exhausted → failure dict
# ---------------------------------------------------------------------------


async def test_returns_failure_after_max_retries():
    validator = MagicMock()
    validator.validate = MagicMock(
        return_value=ValidationResult(is_valid=False, error="Table 'x' does not exist")
    )

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT * FROM x")
    generator.generate_from_prompt = AsyncMock(return_value="SELECT * FROM x")  # keeps failing

    executor = MagicMock()
    executor.execute = AsyncMock()

    corrector = SelfCorrector(generator, validator, executor, _make_settings(max_retries=2))
    result = await corrector.execute_with_correction("Bad question", "sqlite")

    assert result["success"] is False
    assert result["data"] == []
    assert result["attempts"] == 2
    assert len(result["errors"]) == 2
    executor.execute.assert_not_awaited()


# ---------------------------------------------------------------------------
# _fix_sql builds a prompt that includes question, failed SQL, and error
# ---------------------------------------------------------------------------


async def test_fix_sql_prompt_content():
    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT 1")
    generator.generate_from_prompt = AsyncMock(return_value="SELECT 2")

    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    executor = MagicMock()
    # Retryable error message (G6 classifier) so the repair LLM call actually
    # fires and we can inspect the prompt it received.
    executor.execute = AsyncMock(side_effect=[Exception("no such column: foo"), []])

    corrector = SelfCorrector(generator, validator, executor, _make_settings(3))
    await corrector.execute_with_correction("How many users?", "sqlite")

    call_args = generator.generate_from_prompt.call_args[0][0]
    assert "How many users?" in call_args
    assert "SELECT 1" in call_args
    assert "no such column: foo" in call_args


# ---------------------------------------------------------------------------
# G6: error categorization, backoff, char budget
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "msg",
    [
        "no such table: foo",
        "relation does not exist",
        "undefined column 'bar'",
        "column does not exist",
        "ambiguous column reference",
        "operator does not exist",
        "type mismatch in expression",
        "could not be cast to integer",
        "Query timed out",  # asyncio.TimeoutError fallback
    ],
)
def test_is_llm_repairable_returns_true_for_known_marker(msg):
    assert _is_llm_repairable(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        "",
        "permission denied for relation users",
        "connection reset by peer",
        "duplicate key value violates unique constraint",
        "Internal Server Error",
        "deadlock detected",
    ],
)
def test_is_llm_repairable_returns_false_for_fatal(msg):
    assert _is_llm_repairable(msg) is False


async def test_retries_on_undefined_table():
    """Executor raises an UndefinedTable-flavored error → LLM repair fires."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT * FROM nonexistent")
    generator.generate_from_prompt = AsyncMock(return_value="SELECT * FROM users LIMIT 10;")
    generator.get_schema_context = MagicMock(return_value="users(id, name)")

    executor = MagicMock()
    executor.execute = AsyncMock(
        side_effect=[RuntimeError("undefined table 'nonexistent'"), [{"id": 1}]]
    )

    corrector = SelfCorrector(generator, validator, executor, _make_settings(3))
    result = await corrector.execute_with_correction("list users", "sqlite")

    assert result["success"] is True
    assert result["attempts"] == 2
    generator.generate_from_prompt.assert_awaited_once()


async def test_aborts_on_fatal_syntax_error():
    """A non-retryable error category must abort without calling the LLM."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT broken !! syntax")
    generator.generate_from_prompt = AsyncMock(return_value="never called")
    generator.get_schema_context = MagicMock(return_value="users(id)")

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=Exception("permission denied"))

    corrector = SelfCorrector(generator, validator, executor, _make_settings(3))
    result = await corrector.execute_with_correction("anything", "sqlite")

    assert result["success"] is False
    assert result["attempts"] == 1
    generator.generate_from_prompt.assert_not_awaited()
    # The fatal-abort reason is appended to errors.
    assert any("non-retryable" in e.lower() for e in result["errors"])


async def test_backoff_called_between_retries():
    """asyncio.sleep must be called with a positive delay before each LLM repair."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT 1")
    generator.generate_from_prompt = AsyncMock(return_value="SELECT 1")
    generator.get_schema_context = MagicMock(return_value="users(id)")

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=[RuntimeError("no such column: foo"), [{"x": 1}]])

    with patch("src.core.self_corrector.asyncio.sleep", new=AsyncMock()) as sleep_mock:
        corrector = SelfCorrector(generator, validator, executor, _make_settings(3))
        await corrector.execute_with_correction("q", "sqlite")

    assert sleep_mock.await_count >= 1
    # First positional arg is the delay; must be a positive float.
    first_delay = sleep_mock.await_args_list[0].args[0]
    assert first_delay > 0


async def test_aborts_on_char_budget_exhaustion():
    """When the per-request char budget is exceeded, the loop must stop early."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT * FROM nonexistent")
    # Repair returns a long string so the budget is blown after the first repair.
    generator.generate_from_prompt = AsyncMock(return_value="x" * 100)
    generator.get_schema_context = MagicMock(return_value="users(id)")

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=RuntimeError("no such table: foo"))

    # Budget of 10 chars — the very first repair (≫10 chars) blows it.
    settings = _make_settings(max_retries=5, max_chars=10)
    corrector = SelfCorrector(generator, validator, executor, settings)
    result = await corrector.execute_with_correction("q", "sqlite")

    assert result["success"] is False
    assert any("budget exhausted" in e.lower() for e in result["errors"])
    # Should have stopped well before max_retries.
    assert result["attempts"] < 5


# ---------------------------------------------------------------------------
# G9: schema-drift triggers SchemaInspector.refresh() before LLM repair
# ---------------------------------------------------------------------------


async def test_schema_drift_triggers_refresh_before_repair():
    """UndefinedTable error must call inspector.refresh() exactly once
    before the LLM repair attempt."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT * FROM stale_table")
    generator.generate_from_prompt = AsyncMock(return_value="SELECT id FROM users LIMIT 10;")
    generator.get_schema_context = MagicMock(return_value="users(id)")

    executor = MagicMock()
    executor.execute = AsyncMock(
        side_effect=[RuntimeError("undefined table 'stale_table'"), [{"id": 1}]]
    )

    inspector = MagicMock()
    corrector = SelfCorrector(
        generator, validator, executor, _make_settings(3), inspector=inspector
    )
    result = await corrector.execute_with_correction("list users", "sqlite")

    assert result["success"] is True
    inspector.refresh.assert_called_once()
    generator.generate_from_prompt.assert_awaited_once()


async def test_schema_drift_refresh_is_once_per_request():
    """Two drift errors in one request → refresh fires only on the first."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT * FROM s1")
    generator.generate_from_prompt = AsyncMock(side_effect=["SELECT * FROM s2", "SELECT 1"])
    generator.get_schema_context = MagicMock(return_value="users(id)")

    executor = MagicMock()
    executor.execute = AsyncMock(
        side_effect=[
            RuntimeError("no such table: s1"),
            RuntimeError("no such column: x"),
            [{"id": 1}],
        ]
    )

    inspector = MagicMock()
    corrector = SelfCorrector(
        generator, validator, executor, _make_settings(5), inspector=inspector
    )
    result = await corrector.execute_with_correction("q", "sqlite")

    assert result["success"] is True
    inspector.refresh.assert_called_once()


async def test_type_mismatch_does_not_trigger_refresh():
    """Type errors are retryable but not schema drift — refresh must NOT fire."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT CAST(name AS int) FROM users")
    generator.generate_from_prompt = AsyncMock(return_value="SELECT id FROM users")
    generator.get_schema_context = MagicMock(return_value="users(id, name)")

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=[RuntimeError("type mismatch"), [{"id": 1}]])

    inspector = MagicMock()
    corrector = SelfCorrector(
        generator, validator, executor, _make_settings(3), inspector=inspector
    )
    await corrector.execute_with_correction("q", "sqlite")
    inspector.refresh.assert_not_called()


async def test_schema_drift_without_inspector_is_noop():
    """Backwards-compat: without an inspector wired, drift still triggers
    LLM repair — just without a refresh, and without crashing."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT * FROM stale")
    generator.generate_from_prompt = AsyncMock(return_value="SELECT 1")
    generator.get_schema_context = MagicMock(return_value="")

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=[RuntimeError("no such table: stale"), [{"id": 1}]])

    corrector = SelfCorrector(generator, validator, executor, _make_settings(3))
    result = await corrector.execute_with_correction("q", "sqlite")
    assert result["success"] is True


async def test_refresh_failure_does_not_abort_request():
    """If inspector.refresh() itself raises, the request still gets one
    LLM repair attempt against the stale schema."""
    validator = MagicMock()
    validator.validate = MagicMock(return_value=ValidationResult(is_valid=True))

    generator = MagicMock()
    generator.generate = AsyncMock(return_value="SELECT * FROM stale")
    generator.generate_from_prompt = AsyncMock(return_value="SELECT id FROM users")
    generator.get_schema_context = MagicMock(return_value="users(id)")

    executor = MagicMock()
    executor.execute = AsyncMock(side_effect=[RuntimeError("no such table: stale"), [{"id": 1}]])

    inspector = MagicMock()
    inspector.refresh = MagicMock(side_effect=RuntimeError("DB unreachable"))
    corrector = SelfCorrector(
        generator, validator, executor, _make_settings(3), inspector=inspector
    )
    result = await corrector.execute_with_correction("q", "sqlite")

    assert result["success"] is True
    assert any("Schema refresh failed" in e for e in result["errors"])


@pytest.mark.parametrize(
    "msg",
    [
        "no such table: foo",
        "no such column: bar",
        "undefined table 'foo'",
        "undefined column 'bar'",
        "relation does not exist",
        "column does not exist",
        "ambiguous column reference",
        "ambiguous reference to column 'x'",
    ],
)
def test_is_schema_drift_true_for_drift_markers(msg):
    from src.core.self_corrector import _is_schema_drift

    assert _is_schema_drift(msg) is True


@pytest.mark.parametrize(
    "msg",
    [
        "",
        "type mismatch",
        "could not be cast to integer",
        "operator does not exist",
        "query timed out",
        "permission denied",
    ],
)
def test_is_schema_drift_false_for_non_drift(msg):
    from src.core.self_corrector import _is_schema_drift

    assert _is_schema_drift(msg) is False
