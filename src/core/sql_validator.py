"""SQL security validation layer — runs before every query execution."""

import re
from dataclasses import dataclass, field

import sqlparse
import sqlparse.tokens as T

from src.core.schema_inspector import SchemaInspector

# ---------------------------------------------------------------------------
# Security: dangerous functions and statement patterns (T2)
# ---------------------------------------------------------------------------

_FORBIDDEN_FUNCTIONS = {
    # PostgreSQL file/network/RCE
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_connect",
    # SQLite
    "load_extension",
}

_FORBIDDEN_STATEMENT_PATTERNS = [
    re.compile(r"\bCOPY\b.*\bFROM\s+PROGRAM\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bCOPY\b.*\bTO\s+PROGRAM\b", re.IGNORECASE | re.DOTALL),
    re.compile(r"\bATTACH\s+DATABASE\b", re.IGNORECASE),
    re.compile(r"\bDETACH\s+DATABASE\b", re.IGNORECASE),
    re.compile(r"\bSELECT\b.*\bINTO\s+\w", re.IGNORECASE | re.DOTALL),  # SELECT INTO new_table
    re.compile(r"\bPRAGMA\b\s+writable_schema", re.IGNORECASE),
    re.compile(r"\bLOAD_FILE\s*\(", re.IGNORECASE),  # MySQL
    re.compile(r"\bINTO\s+OUTFILE\b", re.IGNORECASE),  # MySQL
    re.compile(r"\bINTO\s+DUMPFILE\b", re.IGNORECASE),  # MySQL
]

# Caught via sqlparse token types (DML / DDL subtypes)
_FORBIDDEN_DML = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "GRANT",
    "REVOKE",
    "EXEC",
    "EXECUTE",
}

# sqlparse does NOT classify these as DML/DDL — checked separately with regex.
# TRUNCATE is classified as T.Keyword (not DDL) by sqlparse, so the token loop above
# misses it. MERGE and the others never appear as DML/DDL tokens either.
_FORBIDDEN_KEYWORD_ONLY = {"EXEC", "EXECUTE", "GRANT", "REVOKE", "TRUNCATE", "MERGE"}

_AGGREGATION_PATTERNS = (
    "GROUP BY",
    "COUNT(",
    "COUNT (",
    "SUM(",
    "SUM (",
    "AVG(",
    "AVG (",
    "MAX(",
    "MAX (",
    "MIN(",
    "MIN (",
)

# ---------------------------------------------------------------------------
# Allowlist: only SELECT (and WITH for CTEs) are valid read-only entry points.
# Every other top-level keyword — COPY, CALL, VACUUM, SET, SHOW, etc. — is
# denied before any other checks run.
# ---------------------------------------------------------------------------

_ALLOWED_FIRST_KEYWORDS = {"SELECT", "WITH"}


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
        # Check 0a: Single statement only — multi-statement strings are rejected.
        parsed_all = sqlparse.parse(sql)
        non_empty = [s for s in parsed_all if s.tokens and str(s).strip()]
        if len(non_empty) > 1:
            return ValidationResult(is_valid=False, error="Only a single SQL statement is allowed")

        # Check 0b: Allowlist — the statement must begin with SELECT or WITH.
        # This is the primary gate against COPY, CALL, VACUUM, SET, SHOW, and
        # any other non-read statement that the blacklist below might miss.
        # WITH is permitted as the CTE prefix for read-only queries; the DML
        # check below (Check 1) still catches writable CTEs such as
        # "WITH d AS (DELETE …) SELECT …".
        first_kw = _first_sql_keyword(sql)
        if first_kw not in _ALLOWED_FIRST_KEYWORDS:
            return ValidationResult(
                is_valid=False,
                error=(
                    f"Only SELECT queries are allowed "
                    f"(statement starts with: {first_kw or 'unknown'})"
                ),
            )

        # Check 0d: Forbidden function scan (T2 — RCE/file-read via DB functions)
        for func_name in _FORBIDDEN_FUNCTIONS:
            if re.search(rf"\b{re.escape(func_name)}\s*\(", sql, re.IGNORECASE):
                return ValidationResult(
                    is_valid=False,
                    error=f"Use of forbidden function '{func_name}' is not allowed",
                )

        # Check 0e: Forbidden statement pattern scan (T2)
        for pattern in _FORBIDDEN_STATEMENT_PATTERNS:
            if pattern.search(sql):
                return ValidationResult(
                    is_valid=False, error="SQL contains a forbidden statement pattern"
                )

        # Check 1: Forbid write operations
        # DML covers INSERT/UPDATE/DELETE; DDL covers CREATE/DROP/ALTER.
        # Both token types must be checked to catch all mutation operations.
        parsed_statements = sqlparse.parse(sql)
        for statement in parsed_statements:
            for token in statement.flatten():
                if (
                    token.ttype in (T.Keyword.DML, T.Keyword.DDL)
                    and token.value.upper() in _FORBIDDEN_DML
                ):
                    return ValidationResult(
                        is_valid=False, error="Write operations are not allowed"
                    )

        # sqlparse classifies EXEC/EXECUTE/GRANT/REVOKE as T.Keyword (no DML/DDL subtype),
        # so the loop above misses them. Catch them with a word-boundary regex.
        # Mask string literals and comments so words inside data (e.g.
        # WHERE feedback = 'please merge my PR') don't trip the keyword scan.
        masked_upper = _mask_strings_and_comments(sql).upper()
        for keyword in _FORBIDDEN_KEYWORD_ONLY:
            if re.search(rf"\b{keyword}\b", masked_upper):
                return ValidationResult(is_valid=False, error="Write operations are not allowed")

        # Check 2: Verify all referenced tables exist
        # Exclude CTE aliases — they are valid references but not real DB tables.
        referenced = _extract_table_names(sql)
        if referenced:
            actual_tables = {t.lower() for t in self._schema_inspector.get_table_names()}
            cte_names = _extract_cte_names(sql)
            for table in referenced:
                if table.lower() not in actual_tables and table.lower() not in cte_names:
                    return ValidationResult(
                        is_valid=False, error=f"Table '{table}' does not exist in the database"
                    )

        # Check 3: Auto-inject LIMIT if the query is a plain SELECT without aggregation.
        # Use a depth-aware check so a LIMIT buried inside a subquery (e.g. "SELECT *
        # FROM (SELECT id FROM users LIMIT 5) AS sub") doesn't fool the outer-query check.
        # Run both scans against the masked SQL so literal data like
        # ``WHERE comment = 'LIMIT 5'`` or ``WHERE note = 'COUNT(*)'`` cannot
        # bypass the safety cap.
        if not _has_top_level_limit(masked_upper) and not any(
            pat in masked_upper for pat in _AGGREGATION_PATTERNS
        ):
            modified = sql.rstrip(";") + " LIMIT 100;"
            return ValidationResult(is_valid=True, warning="No LIMIT added", modified_sql=modified)

        return ValidationResult(is_valid=True)


def _first_sql_keyword(sql: str) -> str:
    """Return the first SQL keyword of *sql*, ignoring comments and whitespace.

    Used by the allowlist check so that ``COPY``, ``CALL``, ``VACUUM``,
    ``SET``, etc. are caught before any token-level scanning.  Returns the
    keyword uppercased, or ``""`` for an empty/comment-only string.
    """
    # Strip single-line comments (-- …)
    stripped = re.sub(r"--[^\n]*", " ", sql)
    # Strip block comments (/* … */)
    stripped = re.sub(r"/\*.*?\*/", " ", stripped, flags=re.DOTALL)
    match = re.match(r"\s*([A-Za-z_]\w*)", stripped)
    return match.group(1).upper() if match else ""


def _extract_table_names(sql: str) -> list[str]:
    """Extract table names from FROM and JOIN clauses using regex.

    Accepts an optional ``schema.`` qualifier and captures only the trailing
    table identifier — schema names are not in ``get_table_names()`` and would
    otherwise fail the existence check.
    """
    pattern = re.compile(
        r"\b(?:FROM|JOIN)\s+(?:[a-zA-Z_][a-zA-Z0-9_]*\s*\.\s*)?([a-zA-Z_][a-zA-Z0-9_]*)",
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


def _mask_strings_and_comments(sql: str) -> str:
    """Replace SQL string literals and comments with spaces of equal length.

    This lets keyword scans see code only, so a literal like
    ``'please merge my PR'`` does not trigger the MERGE block. Double-quoted
    identifiers are preserved (they are names, not data).
    """
    out = list(sql)
    n = len(sql)
    i = 0
    while i < n:
        c = sql[i]
        # -- line comment
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                out[i] = " "
                i += 1
            continue
        # /* block comment */
        if c == "/" and i + 1 < n and sql[i + 1] == "*":
            out[i] = out[i + 1] = " "
            i += 2
            while i + 1 < n and not (sql[i] == "*" and sql[i + 1] == "/"):
                if sql[i] != "\n":
                    out[i] = " "
                i += 1
            if i + 1 < n:
                out[i] = out[i + 1] = " "
                i += 2
            continue
        # 'string' literal — '' is an escaped single quote
        if c == "'":
            out[i] = " "
            i += 1
            while i < n:
                if sql[i] == "'":
                    if i + 1 < n and sql[i + 1] == "'":
                        out[i] = out[i + 1] = " "
                        i += 2
                        continue
                    out[i] = " "
                    i += 1
                    break
                if sql[i] != "\n":
                    out[i] = " "
                i += 1
            continue
        # "quoted identifier" — leave intact (it is a name, not data)
        if c == '"':
            i += 1
            while i < n and sql[i] != '"':
                i += 1
            if i < n:
                i += 1
            continue
        i += 1
    return "".join(out)


def _extract_cte_names(sql: str) -> set[str]:
    """Extract CTE alias names defined in WITH clauses.

    In ``WITH cte_name AS (...)``, ``name AS (`` only appears at CTE definition
    sites — subquery aliases use ``(...) AS name`` (parenthesis on the left),
    so this pattern produces no false positives for ordinary subquery aliases.
    """
    pattern = re.compile(r"\b(\w+)\s+AS\s*\(", re.IGNORECASE)
    return {m.group(1).lower() for m in pattern.finditer(sql)}
