"""Unit tests for SelfCorrector — all LLM/DB calls are mocked."""

from unittest.mock import AsyncMock, MagicMock

from src.core.self_corrector import SelfCorrector
from src.core.sql_validator import ValidationResult


def _make_settings(max_retries: int = 3) -> MagicMock:
    s = MagicMock()
    s.max_self_correction_retries = max_retries
    return s


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
    validator.validate = MagicMock(
        return_value=validate_return or ValidationResult(is_valid=True)
    )

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
        validate_return=ValidationResult(is_valid=True, warning="No LIMIT added", modified_sql=modified_sql),
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
    executor.execute = AsyncMock(
        side_effect=[RuntimeError("no such table: nonexistent"), rows]
    )

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
    executor.execute = AsyncMock(side_effect=[Exception("syntax error"), []])

    corrector = SelfCorrector(generator, validator, executor, _make_settings(3))
    await corrector.execute_with_correction("How many users?", "sqlite")

    call_args = generator.generate_from_prompt.call_args[0][0]
    assert "How many users?" in call_args
    assert "SELECT 1" in call_args
    assert "syntax error" in call_args
