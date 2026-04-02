"""MCP tool: answer a natural-language question against the database."""

from src.core.result_formatter import ResultFormatter
from src.core.self_corrector import SelfCorrector


async def ask_database(
    question: str,
    corrector: SelfCorrector,
    formatter: ResultFormatter,
    dialect: str = "sqlite",
) -> str:
    """Translate *question* to SQL, execute it, and return structured JSON.

    The SelfCorrector handles generation, validation, execution, and
    automatic retry on failure. The ResultFormatter converts the outcome
    to a consistent JSON string for the MCP client.
    """
    result = await corrector.execute_with_correction(question, dialect)

    if result["success"]:
        return formatter.format(result["sql"], result["data"], result["attempts"])

    last_error = (
        result["errors"][-1] if result["errors"] else "Query failed after maximum retries"
    )
    return formatter.format_error(last_error, result["sql"], result["errors"])
