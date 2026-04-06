"""SQL security validation layer — runs before every query execution."""

import re
from dataclasses import dataclass, field

import sqlparse
import sqlparse.tokens as T

from src.core.schema_inspector import SchemaInspector

# Caught via sqlparse token types (DML / DDL subtypes)
_FORBIDDEN_DML = {"INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE", "EXEC", "EXECUTE"}

# sqlparse does NOT classify these as DML/DDL — checked separately with regex.
# TRUNCATE is classified as T.Keyword (not DDL) by sqlparse, so the token loop above
# misses it. MERGE and the others never appear as DML/DDL tokens either.
_FORBIDDEN_KEYWORD_ONLY = {"EXEC", "EXECUTE", "GRANT", "REVOKE", "TRUNCATE", "MERGE"}

_AGGREGATION_PATTERNS = ("GROUP BY", "COUNT(", "COUNT (", "SUM(", "SUM (", "AVG(", "AVG (", "MAX(", "MAX (", "MIN(", "MIN (")


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

        # sqlparse classifies EXEC/EXECUTE/GRANT/REVOKE as T.Keyword (no DML/DDL subtype),
        # so the loop above misses them. Catch them with a word-boundary regex.
        sql_upper = sql.upper()
        for keyword in _FORBIDDEN_KEYWORD_ONLY:
            if re.search(rf"\b{keyword}\b", sql_upper):
                return ValidationResult(is_valid=False, error="Write operations are not allowed")

        # Check 2: Verify all referenced tables exist
        # Exclude CTE aliases — they are valid references but not real DB tables.
        referenced = _extract_table_names(sql)
        if referenced:
            actual_tables = {t.lower() for t in self._schema_inspector.get_table_names()}
            cte_names = _extract_cte_names(sql)
            for table in referenced:
                if table.lower() not in actual_tables and table.lower() not in cte_names:
                    return ValidationResult(is_valid=False, error=f"Table '{table}' does not exist in the database")

        # Check 3: Auto-inject LIMIT if the query is a plain SELECT without aggregation.
        # Use a depth-aware check so a LIMIT buried inside a subquery (e.g. "SELECT *
        # FROM (SELECT id FROM users LIMIT 5) AS sub") doesn't fool the outer-query check.
        sql_upper = sql.upper()
        if not _has_top_level_limit(sql) and not any(pat in sql_upper for pat in _AGGREGATION_PATTERNS):
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


def _has_top_level_limit(sql: str) -> bool:
    """Return True if LIMIT appears at the top level (outside all parentheses).

    A plain string search would be fooled by ``SELECT * FROM (SELECT id FROM t
    LIMIT 5) AS sub`` — the LIMIT is inside a subquery but the outer query is
    still unbounded.  Walking character-by-character and tracking parenthesis
    depth solves this correctly.
    """
    depth = 0
    upper = sql.upper()
    n = len(upper)
    i = 0
    while i < n:
        c = sql[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and upper[i : i + 5] == "LIMIT":
            before_ok = i == 0 or not (upper[i - 1].isalnum() or upper[i - 1] == "_")
            after_ok = (i + 5) >= n or not (upper[i + 5].isalnum() or upper[i + 5] == "_")
            if before_ok and after_ok:
                return True
        i += 1
    return False


def _extract_cte_names(sql: str) -> set[str]:
    """Extract CTE alias names defined in WITH clauses.

    In ``WITH cte_name AS (...)``, ``name AS (`` only appears at CTE definition
    sites — subquery aliases use ``(...) AS name`` (parenthesis on the left),
    so this pattern produces no false positives for ordinary subquery aliases.
    """
    pattern = re.compile(r"\b(\w+)\s+AS\s*\(", re.IGNORECASE)
    return {m.group(1).lower() for m in pattern.finditer(sql)}
