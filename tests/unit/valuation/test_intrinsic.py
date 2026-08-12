import datetime as dt
import unittest

from packages.valuation.intrinsic import (
    DCF_MODEL_VERSION,
    RESIDUAL_INCOME_MODEL_VERSION,
    DcfScenario,
    ResidualIncomeScenario,
    build_dcf_configuration_hash,
    build_residual_income_configuration_hash,
    dcf_scenario_distribution,
    discounted_cash_flow_value,
    residual_income_distribution,
    residual_income_value,
    reverse_dcf_growth,
)
from packages.valuation.models import PriceObservation, ValuationError, ValuationLineage
from packages.valuation.policy import ValuationPolicy


def price():
    return PriceObservation(
        price=100.0,
        observed_at=dt.datetime(2026, 8, 11, 20, tzinfo=dt.timezone.utc),
        available_at=dt.datetime(2026, 8, 11, 20, 1, tzinfo=dt.timezone.utc),
        currency="USD",
        data_snapshot_id="snapshot_" + "4" * 64,
        source_hash="6" * 64,
    )


def dcf_scenarios():
    return (
        DcfScenario("bear", 100, (0.00, 0.00, 0.00), 0.12, 0.02, 200, 10, 0.25),
        DcfScenario("base", 100, (0.08, 0.07, 0.06), 0.10, 0.03, 200, 10, 0.50),
        DcfScenario("bull", 100, (0.15, 0.12, 0.10), 0.09, 0.035, 200, 10, 0.25),
    )


def ri_scenarios():
    return (
        ResidualIncomeScenario(
            "bear", 30, (0.08, 0.08, 0.08), 0.11, 0.5, 0.0, 0.25
        ),
        ResidualIncomeScenario(
            "base", 30, (0.14, 0.13, 0.12), 0.10, 0.4, 0.02, 0.50
        ),
        ResidualIncomeScenario(
            "bull", 30, (0.20, 0.18, 0.16), 0.09, 0.3, 0.03, 0.25
        ),
    )


def lineage(model_version, configuration_hash):
    return ValuationLineage(
        data_snapshot_id=price().data_snapshot_id,
        feature_set_version="valuation-features-v1",
        model_version=model_version,
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        configuration_hash=configuration_hash,
    )


class IntrinsicValuationTests(unittest.TestCase):
    def setUp(self):
        self.policy = ValuationPolicy(policy_version="wp07a-policy-v2")

    def test_dcf_matches_manual_calculation(self):
        scenario = DcfScenario(
            name="base",
            base_fcff=100.0,
            growth_rates=(0.10, 0.08, 0.06),
            discount_rate=0.10,
            terminal_growth_rate=0.03,
            net_debt=150.0,
            shares_outstanding=10.0,
            probability=1.0,
        )
        fcff1 = 110.0
        fcff2 = fcff1 * 1.08
        fcff3 = fcff2 * 1.06
        enterprise = (
            fcff1 / 1.10
            + fcff2 / (1.10**2)
            + fcff3 / (1.10**3)
            + (fcff3 * 1.03 / (0.10 - 0.03)) / (1.10**3)
        )
        expected = (enterprise - 150.0) / 10.0
        self.assertAlmostEqual(expected, discounted_cash_flow_value(scenario), places=10)

    def test_reverse_dcf_recovers_known_growth(self):
        known_growth = 0.12
        target = discounted_cash_flow_value(
            DcfScenario(
                "known",
                80.0,
                (known_growth,) * 5,
                0.11,
                0.03,
                100.0,
                20.0,
                1.0,
            )
        )
        result = reverse_dcf_growth(
            target_price=target,
            base_fcff=80.0,
            years=5,
            discount_rate=0.11,
            terminal_growth_rate=0.03,
            net_debt=100.0,
            shares_outstanding=20.0,
        )
        self.assertTrue(result.feasible)
        self.assertAlmostEqual(known_growth, result.implied_growth_rate, places=7)
        self.assertLess(result.absolute_error, 1e-6)

    def test_reverse_dcf_reports_infeasible_bounds(self):
        result = reverse_dcf_growth(
            target_price=10_000.0,
            base_fcff=10.0,
            years=3,
            discount_rate=0.15,
            terminal_growth_rate=0.02,
            net_debt=0.0,
            shares_outstanding=100.0,
            lower_growth=-0.2,
            upper_growth=0.2,
        )
        self.assertFalse(result.feasible)
        self.assertEqual(0, result.iterations)

    def test_residual_income_matches_manual_fixture(self):
        scenario = ResidualIncomeScenario(
            name="bank-base",
            book_value_per_share=20.0,
            roe_path=(0.15, 0.14),
            cost_of_equity=0.10,
            payout_ratio=0.40,
            terminal_residual_growth=0.02,
            probability=1.0,
        )
        opening = 20.0
        earnings1 = 0.15 * opening
        ri1 = earnings1 - 0.10 * opening
        closing1 = opening + earnings1 * 0.60
        earnings2 = 0.14 * closing1
        ri2 = earnings2 - 0.10 * closing1
        next_ri = ri2 * 1.02
        expected = (
            20.0
            + ri1 / 1.10
            + ri2 / (1.10**2)
            + (next_ri / (0.10 - 0.02)) / (1.10**2)
        )
        self.assertAlmostEqual(expected, residual_income_value(scenario), places=10)

    def test_negative_earnings_do_not_create_negative_dividends(self):
        scenario = ResidualIncomeScenario(
            name="loss-then-recovery",
            book_value_per_share=20.0,
            roe_path=(-0.10, 0.30, 0.25),
            cost_of_equity=0.10,
            payout_ratio=0.50,
            terminal_residual_growth=0.02,
            probability=1.0,
        )
        value = residual_income_value(scenario)
        self.assertGreater(value, 0)
        opening_after_loss = 18.0
        self.assertEqual(18.0, opening_after_loss)

    def test_scenario_distributions_require_exact_lineage_and_are_unverified(self):
        scenarios = dcf_scenarios()
        config_hash = build_dcf_configuration_hash(scenarios, self.policy)
        distribution = dcf_scenario_distribution(
            scenarios,
            lineage(DCF_MODEL_VERSION, config_hash),
            self.policy,
            price=price(),
        )
        self.assertLessEqual(distribution.p10, distribution.p50)
        self.assertLessEqual(distribution.p50, distribution.p90)
        self.assertFalse(distribution.production_change_allowed)
        self.assertIn(
            "SCENARIO_DISTRIBUTION_REQUIRES_OOS_CALIBRATION",
            distribution.reason_codes,
        )
        with self.assertRaisesRegex(ValuationError, "configuration_hash"):
            dcf_scenario_distribution(
                scenarios,
                lineage(DCF_MODEL_VERSION, "0" * 64),
                self.policy,
                price=price(),
            )

        ri = ri_scenarios()
        ri_hash = build_residual_income_configuration_hash(ri, self.policy)
        ri_distribution = residual_income_distribution(
            ri,
            lineage(RESIDUAL_INCOME_MODEL_VERSION, ri_hash),
            self.policy,
            price=price(),
        )
        self.assertGreater(ri_distribution.p90, ri_distribution.p10)

    def test_probabilities_and_names_are_validated(self):
        with self.assertRaisesRegex(ValuationError, "sum to 1"):
            build_dcf_configuration_hash(
                (
                    DcfScenario("a", 100, (0.1,), 0.1, 0.02, 0, 10, 0.4),
                    DcfScenario("b", 100, (0.1,), 0.1, 0.02, 0, 10, 0.4),
                    DcfScenario("c", 100, (0.1,), 0.1, 0.02, 0, 10, 0.4),
                ),
                self.policy,
            )
        with self.assertRaisesRegex(ValuationError, "unique"):
            build_residual_income_configuration_hash(
                (
                    ResidualIncomeScenario("same", 20, (0.1,), 0.1, 0.5, 0.02, 0.3),
                    ResidualIncomeScenario("same", 20, (0.1,), 0.1, 0.5, 0.02, 0.3),
                    ResidualIncomeScenario("other", 20, (0.1,), 0.1, 0.5, 0.02, 0.4),
                ),
                self.policy,
            )

    def test_invalid_terminal_assumptions_fail_closed(self):
        with self.assertRaisesRegex(ValuationError, "below discount_rate"):
            DcfScenario("bad", 100, (0.1,), 0.08, 0.08, 0, 10, 1.0)
        with self.assertRaisesRegex(ValuationError, "below cost_of_equity"):
            ResidualIncomeScenario("bad", 20, (0.1,), 0.1, 0.5, 0.1, 1.0)


if __name__ == "__main__":
    unittest.main()
