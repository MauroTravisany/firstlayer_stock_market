import datetime as dt
import random
from pathlib import Path
import unittest

from packages.valuation.ensemble import combine_valuation_models
from packages.valuation.intrinsic import DcfScenario, discounted_cash_flow_value
from packages.valuation.models import (
    ModelDistribution,
    QualityAssessment,
    QualityState,
    RiskState,
    ValuationLineage,
)
from packages.valuation.policy import ValuationPolicy


ROOT = Path(__file__).resolve().parents[3]
PACKAGE = ROOT / "packages" / "valuation"


def lineage(version):
    return ValuationLineage(
        data_snapshot_id="snapshot_" + "e" * 64,
        feature_set_version="valuation-features-v1",
        model_version=version,
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        peer_universe_hash="f" * 64,
        configuration_hash="1" * 64,
    )


def assessment(score, trap, state, risk):
    return QualityAssessment(
        quality_score=score,
        quality_state=state,
        value_trap_probability=trap,
        risk_state=risk,
        feature_coverage=1.0,
    )


class ValuationSafetyAndPropertyTests(unittest.TestCase):
    def test_package_has_no_network_broker_llm_or_cloud_side_effect_surface(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(PACKAGE.glob("*.py"))
        ).lower()
        for forbidden in (
            "from openai",
            "import openai",
            "google.cloud",
            "alpaca",
            "submit_order",
            "insert_rows_json",
            "client.query(",
            "requests.",
            "urllib.request",
            "socket.",
            "subprocess.",
        ):
            self.assertNotIn(forbidden, source)

    def test_no_ticker_specific_rules_exist_in_valuation_package(self):
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(PACKAGE.glob("*.py"))
        )
        for ticker in ("AAPL", "MSFT", "NVDA", "META", "AMZN", "TSLA"):
            self.assertNotIn(ticker, source)

    def test_quality_changes_do_not_change_fair_value_distribution(self):
        models = (
            ModelDistribution(
                "relative-v1",
                "relative_pe",
                80,
                90,
                100,
                110,
                120,
                0.9,
                lineage("relative-v1"),
                score=0.0,
            ),
            ModelDistribution(
                "fcff-v1",
                "fcff",
                85,
                95,
                105,
                115,
                125,
                0.9,
                lineage("fcff-v1"),
                score=0.1,
            ),
        )
        policy = ValuationPolicy(
            policy_version="wp07a-policy-v1",
            min_confidence=0.0,
        )
        high = combine_valuation_models(
            current_price=100,
            estimates=models,
            quality=assessment(0.95, 0.05, QualityState.ALTA, RiskState.BAJO),
            policy=policy,
        )
        low = combine_valuation_models(
            current_price=100,
            estimates=models,
            quality=assessment(0.10, 0.30, QualityState.BAJA, RiskState.MEDIO),
            policy=policy,
        )
        self.assertEqual(
            (
                high.fair_value_p10,
                high.fair_value_p25,
                high.fair_value_p50,
                high.fair_value_p75,
                high.fair_value_p90,
            ),
            (
                low.fair_value_p10,
                low.fair_value_p25,
                low.fair_value_p50,
                low.fair_value_p75,
                low.fair_value_p90,
            ),
        )
        self.assertNotEqual(high.quality_score, low.quality_score)

    def test_random_ensembles_always_return_monotonic_positive_quantiles(self):
        rng = random.Random(20260812)
        policy = ValuationPolicy(
            policy_version="wp07a-policy-v1",
            min_confidence=0.0,
            max_interval_width_ratio=10.0,
        )
        quality = assessment(
            0.7, 0.1, QualityState.ALTA, RiskState.BAJO
        )
        for case in range(100):
            estimates = []
            for model_index in range(3):
                median = rng.uniform(20, 300)
                lower_spread = rng.uniform(0, median * 0.5)
                upper_spread = rng.uniform(0, median * 0.5)
                values = (
                    max(0.01, median - lower_spread),
                    max(0.01, median - lower_spread * 0.5),
                    median,
                    median + upper_spread * 0.5,
                    median + upper_spread,
                )
                estimates.append(
                    ModelDistribution(
                        model_name=f"model-{case}-{model_index}",
                        model_family=(
                            "relative_pe" if model_index == 0 else "fcff"
                        ),
                        p10=values[0],
                        p25=values[1],
                        p50=values[2],
                        p75=values[3],
                        p90=values[4],
                        confidence=rng.uniform(0.4, 1.0),
                        lineage=lineage(f"model-{case}-{model_index}"),
                        score=rng.uniform(-3, 3),
                    )
                )
            result = combine_valuation_models(
                current_price=rng.uniform(10, 250),
                estimates=tuple(estimates),
                quality=quality,
                policy=policy,
            )
            quantiles = (
                result.fair_value_p10,
                result.fair_value_p25,
                result.fair_value_p50,
                result.fair_value_p75,
                result.fair_value_p90,
            )
            self.assertEqual(tuple(sorted(quantiles)), quantiles)
            self.assertTrue(all(value > 0 for value in quantiles))
            self.assertFalse(result.production_change_allowed)

    def test_dcf_value_increases_with_growth_and_decreases_with_discount_rate(self):
        low_growth = discounted_cash_flow_value(
            DcfScenario(
                "low-growth",
                100,
                (0.02, 0.02, 0.02),
                0.10,
                0.02,
                100,
                10,
                1.0,
            )
        )
        high_growth = discounted_cash_flow_value(
            DcfScenario(
                "high-growth",
                100,
                (0.10, 0.10, 0.10),
                0.10,
                0.02,
                100,
                10,
                1.0,
            )
        )
        high_discount = discounted_cash_flow_value(
            DcfScenario(
                "high-discount",
                100,
                (0.10, 0.10, 0.10),
                0.14,
                0.02,
                100,
                10,
                1.0,
            )
        )
        self.assertGreater(high_growth, low_growth)
        self.assertLess(high_discount, high_growth)


if __name__ == "__main__":
    unittest.main()
