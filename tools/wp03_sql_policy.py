"""Comment-aware lexical and structural checks for compiled GoogleSQL.

The schema graph inspects executable SQL, not documentation embedded in SQL
comments. The helpers keep the original SQL for hashes and BigQuery while using
masked copies for local safety and syntax checks.
"""

from __future__ import annotations

import re
from typing import Any, Pattern, Type


SQL_POLICY_VERSION = "wp03-google-sql-comment-aware-v1"
SQL_STATIC_SYNTAX_POLICY_VERSION = "wp03-google-sql-static-syntax-v1"

# Official GoogleSQL reserved keywords. An unquoted reserved keyword cannot be
# used as an identifier or alias. Keep this set explicit and test its critical
# entries so a parser regression cannot silently reintroduce aliases such as
# ``current`` or ``rows``.
BIGQUERY_RESERVED_KEYWORDS = frozenset(
    {
        "ALL",
        "AND",
        "ANY",
        "ARRAY",
        "AS",
        "ASC",
        "ASSERT_ROWS_MODIFIED",
        "AT",
        "BETWEEN",
        "BY",
        "CASE",
        "CAST",
        "COLLATE",
        "CONTAINS",
        "CREATE",
        "CROSS",
        "CUBE",
        "CURRENT",
        "DEFAULT",
        "DEFINE",
        "DESC",
        "DISTINCT",
        "ELSE",
        "END",
        "ENUM",
        "ESCAPE",
        "EXCEPT",
        "EXCLUDE",
        "EXISTS",
        "EXTRACT",
        "FALSE",
        "FETCH",
        "FOLLOWING",
        "FOR",
        "FROM",
        "FULL",
        "GROUP",
        "GROUPING",
        "GROUPS",
        "HASH",
        "HAVING",
        "IF",
        "IGNORE",
        "IN",
        "INNER",
        "INTERSECT",
        "INTERVAL",
        "INTO",
        "IS",
        "JOIN",
        "LATERAL",
        "LEFT",
        "LIKE",
        "LIMIT",
        "LOOKUP",
        "MERGE",
        "NATURAL",
        "NEW",
        "NO",
        "NOT",
        "NULL",
        "NULLS",
        "OF",
        "ON",
        "OR",
        "ORDER",
        "OUTER",
        "OVER",
        "PARTITION",
        "PRECEDING",
        "PROTO",
        "QUALIFY",
        "RANGE",
        "RECURSIVE",
        "RESPECT",
        "RIGHT",
        "ROLLUP",
        "ROWS",
        "SELECT",
        "SET",
        "SOME",
        "STRUCT",
        "TABLESAMPLE",
        "THEN",
        "TO",
        "TREAT",
        "TRUE",
        "UNBOUNDED",
        "UNION",
        "UNNEST",
        "USING",
        "WHEN",
        "WHERE",
        "WINDOW",
        "WITH",
        "WITHIN",
    }
)

# These tokens can validly follow AS without being aliases, for example
# CAST(x AS ARRAY<STRING>) or SELECT AS STRUCT.
_EXPLICIT_NON_ALIAS_KEYWORDS = frozenset(
    {"ARRAY", "ENUM", "INTERVAL", "PROTO", "RANGE", "STRUCT", "VALUE"}
)

_TABLE_ALIAS_TERMINATORS = frozenset(
    {
        "AT",
        "CROSS",
        "EXCEPT",
        "FOR",
        "FULL",
        "GROUP",
        "HAVING",
        "INNER",
        "INTERSECT",
        "JOIN",
        "LEFT",
        "LIMIT",
        "NATURAL",
        "ON",
        "ORDER",
        "OUTER",
        "PIVOT",
        "QUALIFY",
        "RIGHT",
        "TABLESAMPLE",
        "UNION",
        "UNPIVOT",
        "USING",
        "WHERE",
        "WINDOW",
        "WITH",
    }
)


class SqlLexicalPolicyError(ValueError):
    """Compiled SQL cannot be classified safely by the lexical policy."""


def _masked_character(character: str) -> str:
    return character if character in "\r\n" else " "


def _raise(error_cls: Type[Exception], message: str) -> None:
    raise error_cls(message)


def mask_google_sql_comments(
    sql: str,
    *,
    mask_literals: bool = False,
    mask_identifiers: bool = False,
    error_cls: Type[Exception] = SqlLexicalPolicyError,
    label: str = "compiled SQL",
) -> str:
    """Mask GoogleSQL comments without confusing markers in quoted values.

    Supported comment forms are ``--``, ``#`` and nested ``/* ... */``. Single,
    double, triple-quoted strings and backtick identifiers are recognized.
    Newlines and total character count are preserved so BigQuery locations stay
    comparable to the original SQL. Unterminated comments or quotes fail closed.
    """

    text = str(sql or "")
    output: list[str] = []
    length = len(text)
    index = 0

    while index < length:
        character = text[index]
        following = text[index + 1] if index + 1 < length else ""

        if character == "-" and following == "-":
            output.extend((" ", " "))
            index += 2
            while index < length and text[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue

        if character == "#":
            output.append(" ")
            index += 1
            while index < length and text[index] not in "\r\n":
                output.append(" ")
                index += 1
            continue

        if character == "/" and following == "*":
            depth = 1
            output.extend((" ", " "))
            index += 2
            while index < length and depth:
                character = text[index]
                following = text[index + 1] if index + 1 < length else ""
                if character == "/" and following == "*":
                    depth += 1
                    output.extend((" ", " "))
                    index += 2
                    continue
                if character == "*" and following == "/":
                    depth -= 1
                    output.extend((" ", " "))
                    index += 2
                    continue
                output.append(_masked_character(character))
                index += 1
            if depth:
                _raise(error_cls, f"{label} contains an unterminated block comment")
            continue

        if character in {"'", '"', "`"}:
            quote = character
            triple = text.startswith(quote * 3, index)
            delimiter = quote * (3 if triple else 1)
            is_identifier = quote == "`"
            hide = (mask_literals and not is_identifier) or (
                mask_identifiers and is_identifier
            )
            output.extend(
                _masked_character(value) if hide else value for value in delimiter
            )
            index += len(delimiter)
            closed = False

            while index < length:
                if text[index] == "\\" and index + 1 < length:
                    pair = text[index : index + 2]
                    output.extend(
                        _masked_character(value) if hide else value for value in pair
                    )
                    index += 2
                    continue

                if text.startswith(delimiter, index):
                    output.extend(
                        _masked_character(value) if hide else value
                        for value in delimiter
                    )
                    index += len(delimiter)
                    closed = True
                    break

                if not triple and text.startswith(quote * 2, index):
                    pair = quote * 2
                    output.extend(
                        _masked_character(value) if hide else value for value in pair
                    )
                    index += 2
                    continue

                output.append(
                    _masked_character(text[index]) if hide else text[index]
                )
                index += 1

            if not closed:
                kind = "identifier" if is_identifier else "literal"
                _raise(error_cls, f"{label} contains an unterminated quoted {kind}")
            continue

        output.append(character)
        index += 1

    return "".join(output)


def _executable_sql(
    sql: str,
    *,
    error_cls: Type[Exception],
    label: str,
) -> str:
    masked = mask_google_sql_comments(sql, error_cls=error_cls, label=label)
    if not masked.strip():
        _raise(error_cls, f"{label} contains comments only")
    return masked


def _tokens(sql: str) -> list[tuple[str, str, int]]:
    """Return a small token stream sufficient for structural alias checks."""

    tokens: list[tuple[str, str, int]] = []
    index = 0
    length = len(sql)
    while index < length:
        character = sql[index]
        if character.isspace() or character in {"'", '"'}:
            index += 1
            continue
        if character == "`":
            end = sql.find("`", index + 1)
            if end < 0:
                end = length - 1
            tokens.append(("QUOTED", sql[index : end + 1], index))
            index = end + 1
            continue
        if character.isalpha() or character == "_":
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] == "_"):
                end += 1
            value = sql[index:end]
            tokens.append(("WORD", value.upper(), index))
            index = end
            continue
        if character in "(),.;[]":
            tokens.append((character, character, index))
        index += 1
    return tokens


def _line_column(sql: str, offset: int) -> tuple[int, int]:
    line = sql.count("\n", 0, offset) + 1
    previous_newline = sql.rfind("\n", 0, offset)
    column = offset + 1 if previous_newline < 0 else offset - previous_newline
    return line, column


def _skip_parenthesized(tokens: list[tuple[str, str, int]], index: int) -> int:
    depth = 0
    while index < len(tokens):
        kind = tokens[index][0]
        if kind == "(":
            depth += 1
        elif kind == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return index


def reserved_alias_findings(sql: str) -> tuple[dict[str, object], ...]:
    """Find unquoted reserved identifiers used as CTE, column or table aliases."""

    masked = mask_google_sql_comments(
        sql,
        mask_literals=True,
        label="compiled SQL",
    )
    tokens = _tokens(masked)
    findings: list[dict[str, object]] = []
    seen: set[tuple[str, int]] = set()

    def add(kind: str, token: tuple[str, str, int]) -> None:
        key = (kind, token[2])
        if key in seen:
            return
        seen.add(key)
        line, column = _line_column(sql, token[2])
        findings.append(
            {
                "kind": kind,
                "identifier": token[1],
                "line": line,
                "column": column,
            }
        )

    # CTE and named-window identifiers have the form ``name AS (``.
    for index in range(len(tokens) - 2):
        name, as_token, opening = tokens[index : index + 3]
        if (
            name[0] == "WORD"
            and as_token[:2] == ("WORD", "AS")
            and opening[0] == "("
            and name[1] in BIGQUERY_RESERVED_KEYWORDS
        ):
            add("CTE_OR_WINDOW_ALIAS", name)

    # Explicit aliases (column/table) have ``AS name``. Skip casts and
    # GoogleSQL's SELECT AS STRUCT / SELECT AS VALUE forms.
    for index in range(len(tokens) - 1):
        current_token, candidate = tokens[index], tokens[index + 1]
        if current_token[:2] != ("WORD", "AS") or candidate[0] != "WORD":
            continue
        if candidate[1] in _EXPLICIT_NON_ALIAS_KEYWORDS:
            continue
        if candidate[1] in BIGQUERY_RESERVED_KEYWORDS:
            add("EXPLICIT_ALIAS", candidate)

    # Implicit aliases after FROM/JOIN relations or subqueries.
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token[:2] not in {("WORD", "FROM"), ("WORD", "JOIN")}:
            index += 1
            continue
        cursor = index + 1
        if cursor >= len(tokens):
            break

        if tokens[cursor][0] == "(":
            cursor = _skip_parenthesized(tokens, cursor)
        else:
            # Consume a table path or table-valued function.
            if tokens[cursor][0] not in {"WORD", "QUOTED"}:
                index += 1
                continue
            cursor += 1
            while cursor + 1 < len(tokens) and tokens[cursor][0] == ".":
                cursor += 2
            if cursor < len(tokens) and tokens[cursor][0] == "(":
                cursor = _skip_parenthesized(tokens, cursor)

        if cursor < len(tokens) and tokens[cursor][:2] == ("WORD", "AS"):
            cursor += 1
        if cursor < len(tokens) and tokens[cursor][0] == "WORD":
            candidate = tokens[cursor]
            if candidate[1] not in _TABLE_ALIAS_TERMINATORS:
                if candidate[1] in BIGQUERY_RESERVED_KEYWORDS:
                    add("TABLE_ALIAS", candidate)
        index = max(index + 1, cursor)

    return tuple(findings)


def assert_no_reserved_identifier_aliases(
    sql: str,
    *,
    error_cls: Type[Exception] = SqlLexicalPolicyError,
    label: str = "compiled SQL",
) -> None:
    findings = reserved_alias_findings(sql)
    if not findings:
        return
    rendered = "; ".join(
        f"{item['kind']} {item['identifier']} at "
        f"{item['line']}:{item['column']}"
        for item in findings
    )
    _raise(error_cls, f"{label} uses unquoted GoogleSQL reserved aliases: {rendered}")


def assert_balanced_query_structure(
    sql: str,
    *,
    error_cls: Type[Exception] = SqlLexicalPolicyError,
    label: str = "compiled SQL",
) -> None:
    """Fail closed on unbalanced parentheses, brackets, or CASE expressions."""

    masked = mask_google_sql_comments(
        sql,
        mask_literals=True,
        mask_identifiers=True,
        error_cls=error_cls,
        label=label,
    )
    stacks: dict[str, list[int]] = {"(": [], "[": []}
    closing = {")": "(", "]": "["}
    for offset, character in enumerate(masked):
        if character in stacks:
            stacks[character].append(offset)
        elif character in closing:
            opening = closing[character]
            if not stacks[opening]:
                line, column = _line_column(sql, offset)
                _raise(
                    error_cls,
                    f"{label} has unmatched {character} at {line}:{column}",
                )
            stacks[opening].pop()
    for opening, offsets in stacks.items():
        if offsets:
            line, column = _line_column(sql, offsets[-1])
            _raise(
                error_cls,
                f"{label} has unclosed {opening} at {line}:{column}",
            )

    word_tokens = [value for kind, value, _ in _tokens(masked) if kind == "WORD"]
    if word_tokens.count("CASE") != word_tokens.count("END"):
        _raise(
            error_cls,
            f"{label} has unbalanced CASE/END tokens: "
            f"CASE={word_tokens.count('CASE')} END={word_tokens.count('END')}",
        )


def assert_select_only(
    action: Any,
    *,
    select_pattern: Pattern[str],
    mutating_pattern: Pattern[str],
    error_cls: Type[Exception],
) -> None:
    """Validate a relation/assertion after ignoring valid leading comments."""

    if action.action_type not in {"relation", "assertion"}:
        return
    label = action.target.key
    query = action.sql[0]
    comment_masked = _executable_sql(query, error_cls=error_cls, label=label)
    if not select_pattern.search(comment_masked):
        _raise(
            error_cls,
            f"{label} compiled query must begin with SELECT or WITH after comments",
        )

    policy_scan = mask_google_sql_comments(
        query,
        mask_literals=True,
        mask_identifiers=True,
        error_cls=error_cls,
        label=label,
    )
    if mutating_pattern.search(policy_scan):
        _raise(error_cls, f"{label} contains mutating SQL")
    assert_balanced_query_structure(query, error_cls=error_cls, label=label)
    assert_no_reserved_identifier_aliases(query, error_cls=error_cls, label=label)


def assert_no_operational_write(
    action: Any,
    *,
    project_id: str,
    operational_dataset: str,
    operational_write_pattern: Pattern[str],
    error_cls: Type[Exception],
) -> None:
    """Reject executable writes to the operational dataset, ignoring comments."""

    for query in action.sql:
        policy_scan = mask_google_sql_comments(
            query,
            mask_literals=True,
            error_cls=error_cls,
            label=action.target.key,
        )
        for match in operational_write_pattern.finditer(policy_scan):
            if match.group(1) == project_id and match.group(2) == operational_dataset:
                _raise(
                    error_cls,
                    f"{action.target.key} attempts to mutate the operational dataset",
                )


def assert_raw_operation_scope(
    action: Any,
    *,
    raw_output: str,
    forbidden_statement_pattern: Pattern[str],
    create_table_target_pattern: Pattern[str],
    error_cls: Type[Exception],
) -> None:
    """Validate the sole raw CREATE TABLE operation with comments permitted."""

    if action.action_type != "operations":
        return
    if action.target.name != raw_output:
        _raise(error_cls, f"unexpected operations output {action.target.key}")
    if len(action.sql) != 1:
        _raise(
            error_cls,
            f"{raw_output} must compile to exactly one CREATE TABLE statement",
        )

    query = action.sql[0]
    comment_masked = _executable_sql(
        query,
        error_cls=error_cls,
        label=action.target.key,
    )
    policy_scan = mask_google_sql_comments(
        query,
        mask_literals=True,
        mask_identifiers=True,
        error_cls=error_cls,
        label=action.target.key,
    )
    if forbidden_statement_pattern.search(policy_scan):
        _raise(
            error_cls,
            f"{raw_output} operations SQL contains a forbidden statement",
        )

    assert_balanced_query_structure(
        query,
        error_cls=error_cls,
        label=action.target.key,
    )
    assert_no_reserved_identifier_aliases(
        query,
        error_cls=error_cls,
        label=action.target.key,
    )
    targets = create_table_target_pattern.findall(comment_masked)
    if targets != [action.target.key]:
        _raise(
            error_cls,
            f"{raw_output} must create only {action.target.key}; found {targets}",
        )
