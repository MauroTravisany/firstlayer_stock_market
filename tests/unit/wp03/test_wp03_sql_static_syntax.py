import re
from pathlib import Path
import unittest

from tools import wp03_compiled_sql_semantic_preflight as preflight
from tools import wp03_sql_policy as policy


ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = ROOT / "dataform" / "definitions"


def extract_sqlx_body(text: str) -> str:
    marker = re.search(r"\bconfig\s*\{", text)
    if marker is None:
        raise AssertionError("SQLX file has no config block")
    brace_index = text.find("{", marker.start())
    depth = 0
    quote = None
    escaped = False
    for index in range(brace_index, len(text)):
        character = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                quote = None
            continue
        if character in {"'", '"', "`"}:
            quote = character
            continue
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return text[index + 1 :].strip()
    raise AssertionError("SQLX config block is unterminated")


def normalize_dataform_templates(sql: str, model_name: str) -> str:
    sql = re.sub(
        r'\$\{ref\("([A-Za-z0-9_]+)"\)\}',
        lambda match: f"`stocks-437902.wp03_shadow.{match.group(1)}`",
        sql,
    )
    return sql.replace(
        "${self()}",
        f"`stocks-437902.wp03_shadow.{model_name}`",
    )


class Wp03StaticGoogleSqlTests(unittest.TestCase):
    def test_official_reserved_keyword_set_contains_regression_tokens(self):
        self.assertIn("CURRENT", policy.BIGQUERY_RESERVED_KEYWORDS)
        self.assertIn("ROWS", policy.BIGQUERY_RESERVED_KEYWORDS)
        self.assertIn("RANGE", policy.BIGQUERY_RESERVED_KEYWORDS)
        self.assertEqual(
            "wp03-google-sql-static-syntax-v1",
            policy.SQL_STATIC_SYNTAX_POLICY_VERSION,
        )

    def test_reserved_alias_regression_is_detected(self):
        bad = """
        WITH latest_quarter AS (SELECT 1 AS value)
        SELECT current.*
        FROM latest_quarter current
        """
        findings = policy.reserved_alias_findings(bad)
        self.assertEqual(1, len(findings))
        self.assertEqual("TABLE_ALIAS", findings[0]["kind"])
        self.assertEqual("CURRENT", findings[0]["identifier"])
        with self.assertRaisesRegex(
            policy.SqlLexicalPolicyError,
            "reserved aliases.*CURRENT",
        ):
            policy.assert_no_reserved_identifier_aliases(bad)

    def test_reserved_cte_and_explicit_column_aliases_are_detected(self):
        cases = (
            ("WITH current AS (SELECT 1) SELECT * FROM current", "CURRENT"),
            ("SELECT COUNT(*) AS rows FROM `p.d.t`", "ROWS"),
        )
        for sql, keyword in cases:
            with self.subTest(keyword=keyword):
                with self.assertRaisesRegex(
                    policy.SqlLexicalPolicyError,
                    keyword,
                ):
                    policy.assert_no_reserved_identifier_aliases(sql)

    def test_google_sql_types_and_current_functions_are_not_alias_false_positives(self):
        sql = """
        SELECT
          CAST([] AS ARRAY<STRING>) AS values_array,
          CAST(NULL AS STRUCT<value INT64>) AS value_struct,
          CURRENT_TIMESTAMP() AS calculated_at
        FROM `p.d.t` source_row
        """
        self.assertEqual((), policy.reserved_alias_findings(sql))
        policy.assert_no_reserved_identifier_aliases(sql)
        policy.assert_balanced_query_structure(sql)

    def test_quoted_reserved_alias_is_valid_but_unquoted_is_not(self):
        policy.assert_no_reserved_identifier_aliases(
            "SELECT `current`.* FROM `p.d.t` `current`"
        )
        with self.assertRaisesRegex(
            policy.SqlLexicalPolicyError,
            "CURRENT",
        ):
            policy.assert_no_reserved_identifier_aliases(
                "SELECT current.* FROM `p.d.t` current"
            )

    def test_unbalanced_delimiters_and_case_fail_closed(self):
        invalid = (
            "SELECT (1",
            "SELECT [1, 2",
            "SELECT CASE WHEN TRUE THEN 1",
        )
        for sql in invalid:
            with self.subTest(sql=sql):
                with self.assertRaises(policy.SqlLexicalPolicyError):
                    policy.assert_balanced_query_structure(sql)

    def test_all_wp03_sqlx_sources_pass_static_google_sql_policy(self):
        failures = []
        for model_name in preflight.REQUIRED_OUTPUTS:
            path = DEFINITIONS / f"{model_name}.sqlx"
            try:
                body = extract_sqlx_body(path.read_text(encoding="utf-8"))
                body = normalize_dataform_templates(body, model_name)
                masked = policy.mask_google_sql_comments(
                    body,
                    label=model_name,
                    error_cls=policy.SqlLexicalPolicyError,
                )
                if model_name == preflight.RAW_OUTPUT:
                    if not re.match(r"(?is)^\s*CREATE\s+TABLE\b", masked):
                        raise AssertionError("raw operation does not start with CREATE TABLE")
                elif not re.match(r"(?is)^\s*(?:SELECT|WITH)\b", masked):
                    raise AssertionError("query does not start with SELECT or WITH")
                policy.assert_balanced_query_structure(body, label=model_name)
                policy.assert_no_reserved_identifier_aliases(body, label=model_name)
            except Exception as exc:  # Aggregate every model in one CI failure.
                failures.append(f"{model_name}: {exc}")
        self.assertEqual([], failures, "\n".join(failures))

    def test_financial_context_uses_non_reserved_descriptive_aliases(self):
        text = (
            DEFINITIONS / "trading_financial_context_pit.sqlx"
        ).read_text(encoding="utf-8")
        body = extract_sqlx_body(text)
        self.assertIn("FROM latest_quarter cur_q", body)
        self.assertIn('LEFT JOIN ${ref("financial_quarters_pit")} prior_q', body)
        self.assertNotRegex(body, r"(?i)\bFROM\s+latest_quarter\s+current\b")
        self.assertNotRegex(body, r"(?i)\bcurrent\s*\.")


if __name__ == "__main__":
    unittest.main()
