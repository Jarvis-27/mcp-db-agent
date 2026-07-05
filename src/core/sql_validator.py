"""SQL security validation layer — runs before every query execution."""

import re
from dataclasses import dataclass, field

import sqlparse
from sqlparse.sql import Identifier, IdentifierList, Parenthesis, TokenList
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

# Defense-in-depth (G11): system catalogs / metadata schemas are off-limits
# even when the inspector happens to surface them. Schema names are checked
# against the qualifier of `schema.table`; bare-name tables are checked
# against the table identifier directly.
_FORBIDDEN_SCHEMAS = {
    "pg_catalog",
    "information_schema",
    "mysql",
    "sys",
    "performance_schema",
}
_FORBIDDEN_TABLES = {
    "sqlite_master",
    "sqlite_sequence",
    "sqlite_temp_master",
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
    def __init__(self, schema_inspector: SchemaInspector, max_query_rows: int = 100) -> None:
        self._schema_inspector = schema_inspector
        self._max_query_rows = max_query_rows

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

        # Check 1c (G11): Defense-in-depth — block references to system catalogs
        # and SQLite metadata tables even if the inspector ever surfaces them.
        # Today the existence check rejects these because get_table_names()
        # doesn't expose system catalogs, but that's load-bearing on a single
        # behavior in schema_inspector.py.  This denylist makes the rejection
        # independent of the inspector.
        for schema, table in _extract_qualified_table_refs(sql):
            if schema and schema.lower() in _FORBIDDEN_SCHEMAS:
                return ValidationResult(
                    is_valid=False,
                    error=f"Access to system schema '{schema}' is not allowed",
                )
            if table.lower() in _FORBIDDEN_TABLES:
                return ValidationResult(
                    is_valid=False,
                    error=f"Access to system table '{table}' is not allowed",
                )

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
        has_aggregation = any(pat in masked_upper for pat in _AGGREGATION_PATTERNS)
        top_limit = _extract_top_level_limit(masked_upper)
        if top_limit is None and not has_aggregation:
            modified = sql.rstrip(";") + f" LIMIT {self._max_query_rows};"
            return ValidationResult(is_valid=True, warning="No LIMIT added", modified_sql=modified)

        # Clamp user-supplied LIMIT that exceeds the configured max.
        # Aggregations are exempt — they produce a single row regardless.
        if top_limit is not None and not has_aggregation:
            value, start, end = top_limit
            if value > self._max_query_rows:
                clamped = sql[:start] + str(self._max_query_rows) + sql[end:]
                return ValidationResult(
                    is_valid=True,
                    warning=f"LIMIT clamped from {value} to {self._max_query_rows}",
                    modified_sql=clamped,
                )

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


_RELATION_PREFIX_KEYWORDS = {"LATERAL", "ONLY"}


def _extract_qualified_table_refs(sql: str) -> list[tuple[str, str]]:
    """Return ``[(schema, table)]`` for every FROM/JOIN reference.

    ``schema`` is the empty string when the reference is unqualified.
    """
    refs: list[tuple[str, str]] = []
    for statement in sqlparse.parse(sql):
        refs.extend(_extract_refs_from_tokenlist(statement))
    return refs


def _extract_refs_from_tokenlist(token_list: TokenList) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    expect_relation = False

    for token in token_list.tokens:
        if token.is_whitespace or token.ttype in T.Comment:
            continue

        if _is_relation_keyword(token):
            expect_relation = True
            continue

        if expect_relation:
            if _is_relation_prefix_keyword(token):
                continue
            refs.extend(_extract_refs_from_relation_token(token))
            expect_relation = False
            continue

        if isinstance(token, TokenList):
            refs.extend(_extract_refs_from_tokenlist(token))

    return refs


def _is_relation_keyword(token) -> bool:  # type: ignore[no-untyped-def]
    if not token.is_keyword:
        return False
    keyword = " ".join(str(token.value).upper().split())
    return keyword == "FROM" or keyword == "JOIN" or keyword.endswith(" JOIN")


def _is_relation_prefix_keyword(token) -> bool:  # type: ignore[no-untyped-def]
    if not token.is_keyword:
        return False
    return " ".join(str(token.value).upper().split()) in _RELATION_PREFIX_KEYWORDS


def _extract_refs_from_relation_token(token) -> list[tuple[str, str]]:  # type: ignore[no-untyped-def]
    if isinstance(token, IdentifierList):
        refs: list[tuple[str, str]] = []
        for identifier in token.get_identifiers():
            refs.extend(_extract_refs_from_relation_token(identifier))
        return refs

    if isinstance(token, Identifier):
        if _identifier_contains_subquery(token):
            refs = []
            for child in token.tokens:
                if isinstance(child, Parenthesis):
                    refs.extend(_extract_refs_from_tokenlist(child))
            return refs

        table = _normalize_identifier_name(token.get_real_name() or token.get_name())
        if not table:
            return []
        schema = _normalize_identifier_name(token.get_parent_name())
        return [(schema, table)]

    if isinstance(token, Parenthesis):
        return _extract_refs_from_tokenlist(token)

    if isinstance(token, TokenList):
        return _extract_refs_from_tokenlist(token)

    name = _normalize_identifier_name(str(token.value))
    return [("", name)] if name else []


def _identifier_contains_subquery(identifier: Identifier) -> bool:
    for token in identifier.tokens:
        if isinstance(token, Parenthesis):
            inner = str(token.value)[1:-1]
            if _first_sql_keyword(inner) in _ALLOWED_FIRST_KEYWORDS:
                return True
    return False


def _normalize_identifier_name(name: str | None) -> str:
    if name is None:
        return ""
    value = name.strip()
    if len(value) >= 2:
        if value[0] == '"' and value[-1] == '"':
            return value[1:-1].replace('""', '"')
        if value[0] == "`" and value[-1] == "`":
            return value[1:-1].replace("``", "`")
        if value[0] == "[" and value[-1] == "]":
            return value[1:-1].replace("]]", "]")
    return value


def _extract_table_names(sql: str) -> list[str]:
    """Extract table names from FROM and JOIN clauses.

    Schema qualifiers are dropped — schema names are not in
    ``get_table_names()`` and would otherwise fail the existence check.
    """
    return [table for _, table in _extract_qualified_table_refs(sql)]


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


def _extract_top_level_limit(masked_upper: str) -> tuple[int, int, int] | None:
    """Find the top-level integer LIMIT in *masked_upper* and return its position.

    Returns ``(value, start_idx, end_idx)`` where ``masked_upper[start_idx:end_idx]``
    is the integer literal (the same indices map to the original SQL because
    string masking preserves character offsets).  Returns ``None`` when there is
    no top-level LIMIT, when the value is non-integer (``LIMIT ALL``,
    ``LIMIT ?param``), or when the syntax is MySQL's ``LIMIT offset, count``
    form (which this project does not officially support — bailing out keeps
    the clamp safe-by-omission).
    """
    depth = 0
    n = len(masked_upper)
    i = 0
    while i < n:
        c = masked_upper[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and masked_upper[i : i + 5] == "LIMIT":
            before_ok = i == 0 or not (masked_upper[i - 1].isalnum() or masked_upper[i - 1] == "_")
            after_ok = (i + 5) >= n or not (
                masked_upper[i + 5].isalnum() or masked_upper[i + 5] == "_"
            )
            if before_ok and after_ok:
                j = i + 5
                while j < n and masked_upper[j] in " \t\r\n":
                    j += 1
                start = j
                while j < n and masked_upper[j].isdigit():
                    j += 1
                if j == start:
                    return None
                end = j
                # MySQL "LIMIT offset, count": the first integer is the offset,
                # not the row cap — refuse to clamp rather than truncate offset.
                k = j
                while k < n and masked_upper[k] in " \t\r\n":
                    k += 1
                if k < n and masked_upper[k] == ",":
                    return None
                return (int(masked_upper[start:end]), start, end)
        i += 1
    return None


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
    names: set[str] = set()
    for statement in sqlparse.parse(sql):
        in_cte_list = False
        for token in statement.tokens:
            if token.is_whitespace or token.ttype in T.Comment:
                continue
            if token.ttype == T.Keyword.CTE and str(token.value).upper() == "WITH":
                in_cte_list = True
                continue
            if not in_cte_list:
                continue
            if token.ttype == T.Keyword.DML and str(token.value).upper() == "SELECT":
                break
            if isinstance(token, IdentifierList):
                for identifier in token.get_identifiers():
                    name = _normalize_identifier_name(
                        identifier.get_real_name() or identifier.get_name()
                    )
                    if name:
                        names.add(name.lower())
            elif isinstance(token, Identifier):
                name = _normalize_identifier_name(token.get_real_name() or token.get_name())
                if name:
                    names.add(name.lower())
    return names
