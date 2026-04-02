"""SQL security validation layer — runs before every query execution."""

import re
from dataclasses import dataclass, field

import sqlparse
import sqlparse.tokens as T

from src.core.schema_inspector import SchemaInspector

_FORBIDDEN_DML = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE"}

_AGGREGATION_PATTERNS = ("GROUP BY", "COUNT(", "SUM(", "AVG(", "MAX(", "MIN(")


@dataclass
class ValidationResult:
    is_valid: bool
    error: str | None = field(default=None)
    warning: str | None = field(default=None)
    modified_sql: str | None = field(default=None)


class SQLValidator:
    def __init__(self, schema_inspector: SchemaInspector) -> None:
        self._schema_inspector = schema_inspector

    def validate(self, sql: str) -> ValidationResult:
        # Check 1: Forbid write operations
        # DML covers INSERT/UPDATE/DELETE; DDL covers CREATE/DROP/ALTER.
        # Both token types must be checked to catch all mutation operations.
        parsed_statements = sqlparse.parse(sql)
        for statement in parsed_statements:
            for token in statement.flatten():
                if token.ttype in (T.Keyword.DML, T.Keyword.DDL) and token.value.upper() in _FORBIDDEN_DML:
                    return ValidationResult(is_valid=False, error="Write operations are not allowed")

        # Check 2: Verify all referenced tables exist
        referenced = _extract_table_names(sql)
        if referenced:
            actual_tables = {t.lower() for t in self._schema_inspector.get_table_names()}
            for table in referenced:
                if table.lower() not in actual_tables:
                    return ValidationResult(is_valid=False, error=f"Table '{table}' does not exist in the database")

        # Check 3: Auto-inject LIMIT if the query is a plain SELECT without aggregation
        sql_upper = sql.upper()
        if "LIMIT" not in sql_upper and not any(pat in sql_upper for pat in _AGGREGATION_PATTERNS):
            modified = sql.rstrip(";") + " LIMIT 100;"
            return ValidationResult(is_valid=True, warning="No LIMIT added", modified_sql=modified)

        return ValidationResult(is_valid=True)


def _extract_table_names(sql: str) -> list[str]:
    """Extract table names from FROM and JOIN clauses using regex."""
    # Match: FROM table_name or JOIN table_name (optional alias)
    pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)",
        re.IGNORECASE,
    )
    return pattern.findall(sql)
