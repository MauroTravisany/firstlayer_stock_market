import re
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]
DEFINITIONS = ROOT / "dataform" / "definitions"
SEMANTIC_TOOL = ROOT / "tools" / "wp03_compiled_sql_semantic_preflight.py"
DRY_RUN_RUNBOOK = (
    ROOT
    / "docs"
    / "audit-grade"
    / "runbooks"
    / "WP-03_COMPILED_SQL_DRY_RUN.md"
)
WP03_OUTPUTS = (
    "financial_statements_pit_raw",
    "financial_statements_pit",
    "financial_quarters_pit",
    "financial_ttm_pit",
    "earnings_events_pit",
    "trading_financial_context_pit",
    "trading_earnings_context_pit",
    "portfolio_valuation_pit_shadow",
    "trading_historical_context_pit",
    "wp03_legacy_vs_pit_shadow",
    "wp03_legacy_invalidation",
    "audit_no_lookahead",
)

# This catches the defect that produced:
# "Name ticker is ambiguous inside a".
#
# An explicit join key followed by another relation's unfiltered wildcard can
# silently emit the same field twice. BigQuery may accept the intermediate CTE
# but later reject references such as ``a.ticker`` as ambiguous.
DANGEROUS_JOIN_KEY_WILDCARD = re.compile(
    r"(?m)^[ \t]*(?P<left>[A-Za-z_][A-Za-z0-9_]*)\."
    r"(?P<key>analysis_date|signal_hour|signal_timestamp|"
    r"signal_timestamp_utc|ticker),[ \t]*\n"
    r"^[ \t]*(?P<right>[A-Za-z_][A-Za-z0-9_]*)\.\*"
    r"(?![ \t]+EXCEPT[ \t]*\([^)]*\b(?P=key)\b[^)]*\))"
)


class Wp03SqlProjectionSafetyTests(unittest.TestCase):
    def read(self, target):
        return (DEFINITIONS / f"{target}.sqlx").read_text(encoding="utf-8")

    def test_financial_quarters_excludes_duplicate_ticker_from_statement_star(self):
        sql = self.read("financial_quarters_pit")
        self.assertIn("p.ticker,\n    s.* EXCEPT (ticker),", sql)
        self.assertNotIn("p.ticker,\n    s.*,", sql)

    def test_no_wp03_model_reintroduces_join_keys_through_bare_wildcard(self):
        for target in WP03_OUTPUTS:
            with self.subTest(target=target):
                sql = self.read(target)
                match = DANGEROUS_JOIN_KEY_WILDCARD.search(sql)
                self.assertIsNone(
                    match,
                    (
                        f"{target} projects {match.group('left')}."
                        f"{match.group('key')} and then {match.group('right')}.* "
                        "without excluding the same key"
                        if match
                        else ""
                    ),
                )

    def test_schema_graph_preflight_covers_every_wp03_action(self):
        runbook = DRY_RUN_RUNBOOK.read_text(encoding="utf-8")
        tool = SEMANTIC_TOOL.read_text(encoding="utf-8")
        self.assertIn("dryRun=true", runbook)
        self.assertIn("useLegacySql=false", runbook)
        self.assertIn("WP03_SCHEMA_VALIDATION_WRITE", runbook)
        self.assertIn("ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS", runbook)
        self.assertIn("ZERO_ROW_SCHEMA_VIEW", runbook)
        self.assertIn("ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS", tool)
        self.assertIn("validation_dataset_only", tool)
        for target in WP03_OUTPUTS:
            with self.subTest(target=target):
                self.assertIn(f"`{target}`", runbook)
                self.assertIn(f'"{target}"', tool)


if __name__ == "__main__":
    unittest.main()
