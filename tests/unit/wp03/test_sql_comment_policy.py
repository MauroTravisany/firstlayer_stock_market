import re
from pathlib import Path
import types
import unittest

from tools import wp03_compiled_sql_semantic_preflight as preflight
from tools import wp03_sql_policy as policy


ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = ROOT / "dataform" / "definitions"
PROJECT = "stocks-437902"
OPERATIONAL = "acciones_dataset"
VALIDATION = "acciones_dataset_shadow_wp03_schema_comments"
COMPILATION = (
    "projects/stocks-437902/locations/us-east1/repositories/"
    "portfolio-valuation/compilationResults/comment-policy"
)
SHA = "a" * 40

RELATION_OUTPUTS = tuple(
    name for name in preflight.REQUIRED_OUTPUTS if name != preflight.RAW_OUTPUT
)


def target(name, schema=VALIDATION):
    return {"database": PROJECT, "schema": schema, "name": name}


def relation(name, sql):
    return {
        "target": target(name),
        "canonicalTarget": target(name, OPERATIONAL),
        "filePath": f"definitions/{name}.sqlx",
        "relation": {
            "dependencyTargets": [],
            "disabled": False,
            "selectQuery": sql,
            "relationType": "TABLE",
        },
    }


def operation(sql):
    name = preflight.RAW_OUTPUT
    return {
        "target": target(name),
        "canonicalTarget": target(name, OPERATIONAL),
        "filePath": f"definitions/{name}.sqlx",
        "operations": {
            "dependencyTargets": [],
            "disabled": False,
            "hasOutput": True,
            "queries": [sql],
        },
    }


def action(action_type, sql, name="comment_test"):
    return types.SimpleNamespace(
        action_type=action_type,
        target=types.SimpleNamespace(key=f"{PROJECT}.{VALIDATION}.{name}", name=name),
        sql=(sql,),
    )


def extract_sqlx_body(text):
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


class GoogleSqlCommentPolicyTests(unittest.TestCase):
    def test_all_google_sql_comment_forms_are_allowed_before_select_or_with(self):
        queries = (
            "-- line comment\nWITH x AS (SELECT 1 AS value) SELECT * FROM x",
            "# hash comment\nSELECT 1 AS value",
            "/* block comment with CREATE DROP MERGE */\nSELECT 1 AS value",
            "/* outer /* nested */ comment */\nWITH x AS (SELECT 1) SELECT * FROM x",
        )
        for query in queries:
            with self.subTest(query=query.splitlines()[0]):
                preflight._assert_select_only(action("relation", query))

    def test_comments_with_mutation_words_do_not_trigger_false_positive(self):
        query = (
            "-- DROP TABLE stocks-437902.acciones_dataset.safe\n"
            "/* MERGE UPDATE DELETE CREATE ALTER */\n"
            "SELECT 'DROP MERGE UPDATE' AS documentation"
        )
        current = action("relation", query)
        preflight._assert_select_only(current)
        preflight._assert_no_operational_write(
            current,
            project_id=PROJECT,
            operational_dataset=OPERATIONAL,
        )

    def test_actual_mutation_after_comments_is_rejected(self):
        query = (
            "-- harmless preface\n"
            "WITH x AS (SELECT 1) "
            f"DELETE FROM `{PROJECT}.{OPERATIONAL}.trading_price_features` "
            "WHERE TRUE"
        )
        current = action("relation", query)
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError,
            "mutating SQL",
        ):
            preflight._assert_select_only(current)

    def test_comments_only_and_unterminated_comments_fail_closed(self):
        for query, expected in (
            ("-- only documentation\n# still no query", "comments only"),
            ("/* never closed", "unterminated block comment"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(
                    preflight.SemanticPreflightError,
                    expected,
                ):
                    preflight._assert_select_only(action("relation", query))

    def test_comment_markers_inside_literals_and_identifiers_are_preserved(self):
        query = (
            "SELECT '-- not a comment' AS line_text, "
            "'/* not a block */' AS block_text, "
            "'# not a hash comment' AS hash_text, "
            "r\"\"\"-- still literal /* x */ # y\"\"\" AS raw_text, "
            "`field--identifier`"
        )
        masked = policy.mask_google_sql_comments(query)
        self.assertEqual(query, masked)
        preflight._assert_select_only(action("relation", query))

    def test_raw_operation_accepts_leading_comments_but_preserves_scope_gate(self):
        query = (
            "-- append-only raw contract\n"
            "/* CREATE elsewhere is documentation only */\n"
            f"CREATE TABLE IF NOT EXISTS `{PROJECT}.{VALIDATION}."
            f"{preflight.RAW_OUTPUT}` (revision_id STRING)"
        )
        current = action("operations", query, preflight.RAW_OUTPUT)
        preflight._assert_raw_operation_scope(current)

        wrong = action(
            "operations",
            "-- wrong destination\n"
            f"CREATE TABLE IF NOT EXISTS `{PROJECT}.other_shadow.bad` "
            "(revision_id STRING)",
            preflight.RAW_OUTPUT,
        )
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError,
            "must create only",
        ):
            preflight._assert_raw_operation_scope(wrong)

    def test_plan_accepts_comments_on_every_required_output(self):
        rows = [
            operation(
                "-- raw table documentation\n"
                f"CREATE TABLE IF NOT EXISTS `{PROJECT}.{VALIDATION}."
                f"{preflight.RAW_OUTPUT}` (revision_id STRING)"
            )
        ]
        for index, name in enumerate(RELATION_OUTPUTS):
            prefix = (
                "-- repository-static lineage\n"
                if name == "wp03_legacy_invalidation"
                else (
                    "/* compiled relation documentation */\n"
                    if index % 2 == 0
                    else "# compiled relation documentation\n"
                )
            )
            rows.append(relation(name, prefix + "SELECT 1 AS value"))

        plan, required, assertions = preflight.build_plan(
            rows,
            project_id=PROJECT,
            operational_dataset=OPERATIONAL,
            validation_dataset=VALIDATION,
            compilation_result=COMPILATION,
            git_sha=SHA,
            actions_document_sha256="b" * 64,
        )
        self.assertEqual(12, plan["required_output_count"])
        self.assertEqual(set(preflight.REQUIRED_OUTPUTS), set(required))
        self.assertEqual((), assertions)
        self.assertFalse(plan["production_change_allowed"])

    def test_every_wp03_sqlx_body_has_lexically_valid_comments_and_start(self):
        for name in preflight.REQUIRED_OUTPUTS:
            with self.subTest(name=name):
                text = (DEFINITIONS / f"{name}.sqlx").read_text(encoding="utf-8")
                body = extract_sqlx_body(text)
                masked = policy.mask_google_sql_comments(
                    body,
                    label=name,
                    error_cls=preflight.SemanticPreflightError,
                )
                if name == preflight.RAW_OUTPUT:
                    self.assertRegex(masked, r"(?is)^\s*CREATE\s+TABLE\b")
                else:
                    self.assertRegex(masked, r"(?is)^\s*(?:SELECT|WITH)\b")


if __name__ == "__main__":
    unittest.main()
