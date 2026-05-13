"""Self-correction retry loop — generates, validates, and executes SQL with automatic repair."""

import asyncio
import random

from src.core.schema_inspector import SchemaInspector
from src.core.sql_executor import SQLExecutor
from src.core.sql_generator import SQLGenerator
from src.core.sql_validator import SQLValidator
from src.config import UserSettings


# Substrings, lowercased, of errors the LLM has a reasonable chance of fixing
# given the schema as context.  Anything else (driver-level, network, syntax
# nuance the LLM already generated) is treated as fatal so we don't burn a
# repair round-trip on it.  Matched as case-insensitive substrings.
_RETRYABLE_MARKERS = (
    # PostgreSQL canonical messages
    "undefined table",
    "undefined column",
    "ambiguous column",
    "ambiguous reference",
    "column does not exist",
    "relation does not exist",
    "operator does not exist",
    # SQLite canonical messages
    "no such table",
    "no such column",
    # Common across drivers
    "type mismatch",
    "could not be cast",
    "cannot be cast",
    # asyncio TimeoutError surfaces empty / "Query timed out" — retry once is fine
    "query timed out",
)


def _is_llm_repairable(error_msg: str) -> bool:
    """Return True when *error_msg* names a class of error the LLM can plausibly fix.

    Used to skip the repair round-trip on fatal errors (driver issues, auth
    errors, internal exceptions) where the LLM has no information that would
    change the outcome.
    """
    if not error_msg:
        return False
    lower = error_msg.lower()
    return any(marker in lower for marker in _RETRYABLE_MARKERS)


# Strict subset of _RETRYABLE_MARKERS — errors whose root cause is the cached
# schema being out of date.  Type-mismatch / cast / timeout errors are NOT
# here: they're query-author bugs, refreshing the schema can't help.
_SCHEMA_DRIFT_MARKERS = (
    "undefined table",
    "undefined column",
    "relation does not exist",
    "column does not exist",
    "ambiguous column",
    "ambiguous reference",
    "no such table",
    "no such column",
)


def _is_schema_drift(error_msg: str) -> bool:
    """Return True when *error_msg* indicates the cached schema is stale (G9)."""
    if not error_msg:
        return False
    lower = error_msg.lower()
    return any(marker in lower for marker in _SCHEMA_DRIFT_MARKERS)


class SelfCorrector:
    def __init__(
        self,
        generator: SQLGenerator,
        validator: SQLValidator,
        executor: SQLExecutor,
        settings: UserSettings,
        inspector: SchemaInspector | None = None,
    ) -> None:
        self._generator = generator
        self._validator = validator
        self._executor = executor
        self._inspector = inspector
        self._max_retries = settings.max_self_correction_retries
        self._max_chars = getattr(settings, "max_llm_chars_per_request", 40_000)

    async def execute_with_correction(
        self, question: str, dialect: str = "sqlite"
    ) -> dict[str, object]:
        """Generate SQL for *question*, validate, execute, and self-correct on failure.

        Returns a dict with keys:
        - success (bool)
        - sql (str): last attempted SQL
        - data (list[dict]): rows on success, empty list on failure
        - attempts (int): number of loop iterations used
        - errors (list[str]): accumulated error messages (always present)
        """
        sql = await self._generator.generate(question, dialect)
        errors_so_far: list[str] = []
        chars_consumed = 0
        schema_refreshed = False
        attempt = 0

        while attempt < self._max_retries:
            attempt += 1

            # --- Validation ---
            validation = self._validator.validate(sql)
            if not validation.is_valid:
                errors_so_far.append(validation.error or "Validation failed")
                if chars_consumed > self._max_chars:
                    errors_so_far.append(
                        f"Aborted: per-request LLM budget exhausted "
                        f"({chars_consumed} > {self._max_chars} chars)"
                    )
                    break
                await self._sleep_backoff(attempt)
                try:
                    sql, used = await self._fix_sql(
                        question, sql, validation.error or "Validation failed", errors_so_far
                    )
                    chars_consumed += used
                except Exception as fix_exc:
                    errors_so_far.append(f"Self-correction LLM call failed: {fix_exc}")
                    break
                continue

            # Use the LIMIT-injected or clamped version if the validator produced one
            if validation.modified_sql:
                sql = validation.modified_sql

            # --- Execution ---
            try:
                data = await self._executor.execute(sql)
                return {
                    "success": True,
                    "sql": sql,
                    "data": data,
                    "attempts": attempt,
                    "errors": errors_so_far,
                }
            except Exception as exc:
                # asyncio.TimeoutError.__str__() returns "" in Python 3.11+,
                # which gives the LLM no context to correct.  Use a fallback.
                error_msg = str(exc) or "Query timed out"
                errors_so_far.append(error_msg)
                if not _is_llm_repairable(error_msg):
                    errors_so_far.append(f"Aborted: non-retryable error category ({error_msg})")
                    break

                # G9: bust the cached schema once per request when the live DB
                # tells us our cache is stale, so _fix_sql below sees fresh
                # schema via generator.get_schema_context().
                if (
                    not schema_refreshed
                    and self._inspector is not None
                    and _is_schema_drift(error_msg)
                ):
                    try:
                        self._inspector.refresh()
                        schema_refreshed = True
                    except Exception as refresh_exc:
                        errors_so_far.append(f"Schema refresh failed: {refresh_exc}")

                if chars_consumed > self._max_chars:
                    errors_so_far.append(
                        f"Aborted: per-request LLM budget exhausted "
                        f"({chars_consumed} > {self._max_chars} chars)"
                    )
                    break
                await self._sleep_backoff(attempt)
                try:
                    sql, used = await self._fix_sql(question, sql, error_msg, errors_so_far)
                    chars_consumed += used
                except Exception as fix_exc:
                    errors_so_far.append(f"Self-correction LLM call failed: {fix_exc}")
                    break

        # All retries exhausted
        return {
            "success": False,
            "sql": sql,
            "data": [],
            "attempts": attempt,
            "errors": errors_so_far,
        }

    @staticmethod
    async def _sleep_backoff(attempt: int) -> None:
        # 0.5s, 1.0s, 1.5s … with up to 300ms of jitter to absorb upstream throttle.
        delay = 0.5 * attempt + random.uniform(0, 0.3)
        await asyncio.sleep(delay)

    async def _fix_sql(
        self,
        question: str,
        failed_sql: str,
        error: str,
        error_history: list[str],
    ) -> tuple[str, int]:
        """Ask the LLM to repair *failed_sql* given the error context.

        Returns ``(repaired_sql, chars_consumed)`` so the caller can track a
        soft per-request budget.  ``chars_consumed`` is the prompt length plus
        the response length — a cheap heuristic that avoids changing the
        SQLGenerator return shape.
        """
        schema = self._generator.get_schema_context()
        history_lines = "\n".join(f"- {e}" for e in error_history)
        prompt = (
            "You are a SQL expert. Fix the SQL query below so it no longer produces the given error.\n\n"
            f"Original question: {question}\n\n"
            f"Database schema:\n{schema}\n\n"
            f"Failed SQL:\n{failed_sql}\n\n"
            f"Error: {error}\n\n"
            f"Previous errors in this session:\n{history_lines}\n\n"
            "Return ONLY the corrected SQL with no explanation, markdown, or backticks."
        )
        repaired = await self._generator.generate_from_prompt(prompt)
        return repaired, len(prompt) + len(repaired)
