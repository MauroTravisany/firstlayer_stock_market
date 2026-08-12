import unittest

from packages.valuation.models import QualityState, RiskState
from packages.valuation.quality import QualityInputs, assess_quality


class QualityAssessmentTests(unittest.TestCase):
    def test_high_quality_low_risk_company(self):
        result = assess_quality(
            QualityInputs(
                gross_profitability=0.55,
                roic=0.24,
                wacc=0.09,
                free_cash_flow_margin=0.22,
                cash_conversion=1.0,
                margin_stability=0.90,
                net_debt_to_ebitda=0.5,
                interest_coverage=18.0,
                accruals_ratio=0.01,
                revenue_growth=0.12,
                earnings_revision=0.05,
                operating_margin_change=0.02,
            )
        )
        self.assertEqual(QualityState.ALTA, result.quality_state)
        self.assertEqual(RiskState.BAJO, result.risk_state)
        self.assertGreater(result.quality_score, 0.75)
        self.assertLess(result.value_trap_probability, 0.35)
        self.assertEqual(1.0, result.feature_coverage)

    def test_value_trap_risk_is_independent_of_quality_label(self):
        result = assess_quality(
            QualityInputs(
                gross_profitability=0.50,
                roic=0.18,
                wacc=0.10,
                free_cash_flow_margin=-0.12,
                cash_conversion=0.40,
                margin_stability=0.55,
                net_debt_to_ebitda=6.0,
                interest_coverage=0.8,
                accruals_ratio=0.20,
                revenue_growth=-0.18,
                earnings_revision=-0.25,
                operating_margin_change=-0.12,
            )
        )
        self.assertEqual(RiskState.ALTO, result.risk_state)
        self.assertGreater(result.value_trap_probability, 0.65)
        self.assertIn("VALUE_TRAP_RISK_HIGH", result.reason_codes)
        self.assertIn("NEGATIVE_FREE_CASH_FLOW_MARGIN", result.reason_codes)

    def test_missing_data_produces_explicit_insufficient_states(self):
        result = assess_quality(
            QualityInputs(gross_profitability=0.30, roic=0.12)
        )
        self.assertEqual(
            QualityState.DATOS_INSUFICIENTES, result.quality_state
        )
        self.assertEqual(RiskState.DESCONOCIDO, result.risk_state)
        self.assertLess(result.feature_coverage, 0.5)
        self.assertIn("QUALITY_FEATURE_COVERAGE_LOW", result.reason_codes)
        self.assertIn(
            "VALUE_TRAP_FEATURE_COVERAGE_LOW", result.reason_codes
        )

    def test_same_inputs_are_deterministic(self):
        inputs = QualityInputs(
            gross_profitability=0.35,
            roic=0.15,
            wacc=0.09,
            free_cash_flow_margin=0.10,
            cash_conversion=0.8,
            margin_stability=0.7,
            net_debt_to_ebitda=2.0,
            interest_coverage=6.0,
            accruals_ratio=0.03,
            revenue_growth=0.05,
            earnings_revision=0.0,
            operating_margin_change=0.0,
        )
        first = assess_quality(inputs)
        second = assess_quality(inputs)
        self.assertEqual(first, second)
        self.assertEqual(first.assessment_hash, second.assessment_hash)


if __name__ == "__main__":
    unittest.main()
