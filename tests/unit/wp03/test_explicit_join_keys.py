import re
from pathlib import Path
import types
import unittest

from tools import wp03_compiled_sql_semantic_preflight as preflight
from tools import wp03_join_policy as join_policy


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


def read_body(model_name: str) -> str:
    path = DEFINITIONS / f"{model_name}.sqlx"
    return extract_sqlx_body(path.read_text(encoding="utf-8"))


class Wp03ExplicitJoinKeyTests(unittest.TestCase):
    def test_policy_version_is_stable(self):
        self.assertEqual(
            "wp03-explicit-join-keys-v1",
            join_policy.JOIN_KEY_POLICY_VERSION,
        )
        self.assertEqual(
            join_policy.JOIN_KEY_POLICY_VERSION,
            preflight.JOIN_KEY_POLICY_VERSION,
        )

    def test_join_using_regression_is_rejected(self):
        sql = """
        SELECT p.analysis_date
        FROM pit p
        LEFT JOIN legacy l
          USING (analysis_date, signal_hour, ticker)
        LEFT JOIN valuation v
          USING (analysis_date, signal_hour, ticker)
        """
        findings = join_policy.using_join_findings(sql)
        self.assertEqual(2, len(findings))
        with self.assertRaisesRegex(
            join_policy.JoinKeyPolicyError,
            "requires explicit qualified ON predicates",
        ):
            join_policy.assert_explicit_join_predicates(sql)

    def test_comments_and_literals_do_not_trigger_false_positive(self):
        sql = """
        -- USING (analysis_date) is documentation only.
        SELECT "USING (ticker)" AS explanation
        FROM `project.dataset.table` source_row
        """
        self.assertEqual((), join_policy.using_join_findings(sql))
        join_policy.assert_explicit_join_predicates(sql)

    def test_schema_plan_hook_rejects_compiled_using(self):
        action = types.SimpleNamespace(
            action_type="relation",
            target=types.SimpleNamespace(
                key="stocks-437902.wp03_shadow.bad_join"
            ),
            sql=(
                "SELECT p.analysis_date FROM `p.d.left` p "
                "LEFT JOIN `p.d.right` r USING (analysis_date)",
            ),
        )
        with self.assertRaisesRegex(
            preflight.SemanticPreflightError,
            "JOIN USING",
        ):
            preflight._assert_select_only(action)

    def test_all_wp03_sources_use_explicit_on_predicates(self):
        failures = []
        for model_name in preflight.REQUIRED_OUTPUTS:
            body = read_body(model_name)
            findings = join_policy.using_join_findings(
                body,
                label=model_name,
            )
            if findings:
                locations = ", ".join(
                    f"{item['line']}:{item['column']}" for item in findings
                )
                failures.append(f"{model_name}: JOIN USING at {locations}")
        self.assertEqual([], failures, "\n".join(failures))

    def test_legacy_comparison_has_fully_qualified_join_keys(self):
        body = read_body("wp03_legacy_vs_pit_shadow")
        for marker in (
            "ON l.analysis_date = p.analysis_date",
            "AND l.signal_hour = p.signal_hour",
            "AND l.ticker = p.ticker",
            "ON pv.analysis_date = p.analysis_date",
            "AND pv.signal_hour = p.signal_hour",
            "AND pv.ticker = p.ticker",
        ):
            self.assertIn(marker, body)

    def test_other_multi_join_models_have_explicit_key_ownership(self):
        earnings = read_body("trading_earnings_context_pit")
        valuation = read_body("portfolio_valuation_pit_shadow")
        for marker in (
            "ON x.analysis_date = p.analysis_date",
            "AND x.signal_hour = p.signal_hour",
            "AND x.ticker = p.ticker",
            "ON r.analysis_date = p.analysis_date",
            "AND r.signal_hour = p.signal_hour",
            "AND r.ticker = p.ticker",
        ):
            self.assertIn(marker, earnings)
        for marker in (
            "ON t.analysis_date = p.analysis_date",
            "AND t.signal_hour = p.signal_hour",
            "AND t.ticker = p.ticker",
        ):
            self.assertIn(marker, valuation)


if __name__ == "__main__":
    unittest.main()
