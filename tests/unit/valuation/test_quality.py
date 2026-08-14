import datetime as dt
import unittest

from packages.valuation.calibration import (
    ProbabilityForecast,
    RiskCalibrationEvidence,
    bind_risk_calibration,
    probability_calibration_report,
)
from packages.valuation.models import CalibrationStatus, QualityState, RiskState, ValuationLineage
from packages.valuation.quality import (
    QUALITY_CONFIGURATION_HASH,
    QUALITY_MODEL_VERSION,
    QualityInputs,
    assess_quality,
)


def lineage():
    return ValuationLineage(
        data_snapshot_id="snapshot_" + "a" * 64,
        feature_set_version="valuation-features-v1",
        model_version=QUALITY_MODEL_VERSION,
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        configuration_hash=QUALITY_CONFIGURATION_HASH,
    )


def passing_report():
    rows = []
    for _ in range(20):
        rows.extend(
            [
                ProbabilityForecast(0.2, False),
                ProbabilityForecast(0.2, False),
                ProbabilityForecast(0.2, False),
                ProbabilityForecast(0.2, False),
                ProbabilityForecast(0.2, True),
                ProbabilityForecast(0.8, True),
                ProbabilityForecast(0.8, True),
                ProbabilityForecast(0.8, True),
                ProbabilityForecast(0.8, True),
                ProbabilityForecast(0.8, False),
            ]
        )
    return probability_calibration_report(rows, min_samples=100)


class QualityAssessmentTests(unittest.TestCase):
    def test_high_quality_low_heuristic_risk_remains_unknown_until_calibrated(self):
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
            ),
            lineage(),
        )
        self.assertEqual(QualityState.ALTA, result.quality_state)
        self.assertEqual(RiskState.DESCONOCIDO, result.risk_state)
        self.assertEqual(CalibrationStatus.UNVERIFIED, result.risk_calibration_status)
        self.assertGreater(result.quality_score, 0.75)
        self.assertLess(result.value_trap_probability, 0.35)
        self.assertEqual(1.0, result.feature_coverage)
        self.assertEqual(1.0, result.risk_feature_coverage)
        self.assertIn("VALUE_TRAP_MODEL_UNCALIBRATED", result.reason_codes)

    def test_high_value_trap_warning_fails_closed_even_before_calibration(self):
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
            ),
            lineage(),
        )
        self.assertEqual(RiskState.ALTO, result.risk_state)
        self.assertGreater(result.value_trap_probability, 0.65)
        self.assertIn("VALUE_TRAP_RISK_HIGH", result.reason_codes)

    def test_missing_data_produces_explicit_insufficient_states(self):
        result = assess_quality(
            QualityInputs(gross_profitability=0.30, roic=0.12),
            lineage(),
        )
        self.assertEqual(QualityState.DATOS_INSUFICIENTES, result.quality_state)
        self.assertEqual(RiskState.DESCONOCIDO, result.risk_state)
        self.assertLess(result.feature_coverage, 0.5)
        self.assertIn("QUALITY_FEATURE_COVERAGE_LOW", result.reason_codes)
        self.assertIn("VALUE_TRAP_FEATURE_COVERAGE_LOW", result.reason_codes)

    def test_binding_calibration_can_establish_low_risk_state(self):
        assessment = assess_quality(
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
            ),
            lineage(),
        )
        evidence = RiskCalibrationEvidence(
            evidence_version="risk-calibration-v1",
            risk_model_spec_hash=assessment.risk_model_spec_hash,
            calibration_snapshot_id="snapshot_" + "b" * 64,
            evaluation_split_id="outer-validation-v1",
            target_definition_hash="c" * 64,
            calibration_cutoff_at=dt.datetime(2026, 8, 10, tzinfo=dt.timezone.utc),
            probability_report=passing_report(),
        )
        bound = bind_risk_calibration(assessment, evidence)
        self.assertEqual(CalibrationStatus.PASS, bound.risk_calibration_status)
        self.assertEqual(RiskState.BAJO, bound.risk_state)
        self.assertEqual(evidence.evidence_hash, bound.risk_calibration_hash)
        self.assertNotEqual(assessment.assessment_hash, bound.assessment_hash)

    def test_same_inputs_and_lineage_are_deterministic(self):
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
        first = assess_quality(inputs, lineage())
        second = assess_quality(inputs, lineage())
        self.assertEqual(first, second)
        self.assertEqual(first.assessment_hash, second.assessment_hash)


if __name__ == "__main__":
    unittest.main()
