"""Comment-aware lexical policy checks for compiled GoogleSQL.

The schema graph must inspect the executable SQL, not documentation embedded in
SQL comments. These helpers mask comments for policy checks while preserving
the original SQL for hashing and BigQuery validation. String literals are
optionally masked for keyword scans so words such as ``DROP`` in a reason code
do not look like executable statements.
"""

from __future__ import annotations

from typing import Any, Pattern, Type


SQL_POLICY_VERSION = "wp03-google-sql-comment-aware-v1"


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
    """Mask GoogleSQL comments without confusing comment markers in literals.

    Supported comment forms are ``--``, ``#`` and ``/* ... */``. Single,
    double, triple-quoted strings and backtick identifiers are recognized.
    Newlines and total character count are preserved, which keeps BigQuery
    error locations comparable to the original SQL.

    When ``mask_literals`` is true, quoted string literals are masked as well;
    backtick identifiers remain visible unless ``mask_identifiers`` is true.
    Unterminated block comments or quoted values fail closed.
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
    masked = mask_google_sql_comments(
        sql,
        error_cls=error_cls,
        label=label,
    )
    if not masked.strip():
        _raise(error_cls, f"{label} contains comments only")
    return masked


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

    targets = create_table_target_pattern.findall(comment_masked)
    if targets != [action.target.key]:
        _raise(
            error_cls,
            f"{raw_output} must create only {action.target.key}; found {targets}",
        )
