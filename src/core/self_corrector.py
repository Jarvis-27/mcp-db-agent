"""Self-correction retry loop — generates, validates, and executes SQL with automatic repair."""

from src.core.sql_executor import SQLExecutor
from src.core.sql_generator import SQLGenerator
from src.core.sql_validator import SQLValidator
from src.config import Settings


class SelfCorrector:
    def __init__(
        self,
        generator: SQLGenerator,
        validator: SQLValidator,
        executor: SQLExecutor,
        settings: Settings,
    ) -> None:
        self._generator = generator
        self._validator = validator
        self._executor = executor
        self._max_retries = settings.max_self_correction_retries

    async def execute_with_correction(self, question: str, dialect: str = "sqlite") -> dict[str, object]:
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
        attempt = 0

        while attempt < self._max_retries:
            attempt += 1

            # --- Validation ---
            validation = self._validator.validate(sql)
            if not validation.is_valid:
                errors_so_far.append(validation.error or "Validation failed")
                try:
                    sql = await self._fix_sql(
                        question, sql, validation.error or "Validation failed", errors_so_far
                    )
                except Exception as fix_exc:
                    errors_so_far.append(f"Self-correction LLM call failed: {fix_exc}")
                    break
                continue

            # Use the LIMIT-injected version if the validator produced one
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
                try:
                    sql = await self._fix_sql(question, sql, error_msg, errors_so_far)
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

    async def _fix_sql(
        self,
        question: str,
        failed_sql: str,
        error: str,
        error_history: list[str],
    ) -> str:
        """Ask the LLM to repair *failed_sql* given the error context.

        The full database schema is included so the LLM can reference correct
        table and column names when the original failure was a name error.
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
        return await self._generator.generate_from_prompt(prompt)
