"""SQL generation from natural language using an LLM backend."""

import re

import anthropic
import groq

from src.config import Settings
from src.core.schema_inspector import SchemaInspector


class SQLGenerator:
    def __init__(self, settings: Settings, schema_inspector: SchemaInspector) -> None:
        self._settings = settings
        self._schema_inspector = schema_inspector

        if settings.llm_provider == "groq":
            self._client = groq.AsyncGroq(api_key=settings.groq_api_key)
        else:
            self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    def _build_prompt(self, question: str, dialect: str) -> str:
        schema = self._schema_inspector.get_full_schema()
        return (
            f"You are a SQL expert.\n\n"
            f"Database schema:\n{schema}\n\n"
            f"Target SQL dialect: {dialect}\n\n"
            f"Rules:\n"
            f"1. Use only tables and columns that exist in the schema above.\n"
            f"2. Always alias tables (e.g. FROM users u).\n"
            f"3. Add LIMIT unless the query is an aggregation (GROUP BY, COUNT, SUM, AVG, MAX, MIN).\n"
            f"4. Use the correct date functions for the {dialect} dialect.\n"
            f"5. Use LEFT JOIN when the related rows may be missing.\n"
            f"6. Return ONLY raw SQL with no markdown, backticks, or explanation.\n\n"
            f"Question: {question}"
        )

    async def generate_from_prompt(self, prompt: str) -> str:
        """Call the LLM with a pre-built prompt and return cleaned SQL.

        Used by SelfCorrector to send correction prompts that include error
        context not available through the standard generate() path.
        """
        return await self._call_llm(prompt)

    async def generate(self, question: str, dialect: str = "sqlite") -> str:
        return await self._call_llm(self._build_prompt(question, dialect))

    async def _call_llm(self, prompt: str) -> str:
        """Send *prompt* to the configured LLM and return cleaned SQL."""
        if isinstance(self._client, groq.AsyncGroq):
            response = await self._client.chat.completions.create(
                model=self._settings.groq_model,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": "You are a SQL expert. Return only SQL."},
                    {"role": "user", "content": prompt},
                ],
            )
            raw_sql = response.choices[0].message.content or ""
        else:
            response = await self._client.messages.create(
                model=self._settings.claude_model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            block = response.content[0]
            raw_sql = block.text if isinstance(block, anthropic.types.TextBlock) else ""

        return _clean_sql(raw_sql)


def _clean_sql(sql: str) -> str:
    """Strip markdown fences, backticks, and surrounding whitespace."""
    sql = sql.strip()
    # Remove ```sql ... ``` or ``` ... ``` fences
    sql = re.sub(r"^```(?:sql)?\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"\s*```$", "", sql)
    return sql.strip("`").strip()
