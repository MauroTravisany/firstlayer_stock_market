import datetime as dt
import unittest

from packages.valuation.models import ModelDistribution, ValuationLineage
from packages.valuation.routing import EntityType, validate_model_route


def lineage(version):
    return ValuationLineage(
        data_snapshot_id="snapshot_" + "9" * 64,
        feature_set_version="valuation-features-v1",
        model_version=version,
        source_cutoff_at=dt.datetime(2026, 8, 12, tzinfo=dt.timezone.utc),
        currency="USD",
        peer_universe_hash="8" * 64,
        configuration_hash="7" * 64,
    )


def model(name, family):
    return ModelDistribution(
        model_name=name,
        model_family=family,
        p10=80,
        p25=90,
        p50=100,
        p75=110,
        p90=120,
        confidence=0.8,
        lineage=lineage(name),
    )


class RoutingTests(unittest.TestCase):
    def test_general_company_requires_relative_and_intrinsic(self):
        result = validate_model_route(
            EntityType.GENERAL_CORPORATE,
            (model("relative-v1", "relative_pe"), model("fcff-v1", "fcff")),
        )
        self.assertEqual("PASS", result.status)
        missing = validate_model_route(
            EntityType.GENERAL_CORPORATE,
            (model("relative-v1", "relative_pe"),),
        )
        self.assertEqual("FAIL", missing.status)
        self.assertIn(
            "VALUATION_ROUTE_REQUIRED_MODEL_MISSING",
            missing.reason_codes,
        )

    def test_bank_route_rejects_fcff_and_requires_residual_income(self):
        valid = validate_model_route(
            EntityType.BANK_INSURER,
            (
                model("pb-v1", "relative_pb"),
                model("ri-v1", "residual_income"),
            ),
        )
        self.assertEqual("PASS", valid.status)
        invalid = validate_model_route(
            EntityType.BANK_INSURER,
            (
                model("pb-v1", "relative_pb"),
                model("fcff-v1", "fcff"),
            ),
        )
        self.assertEqual("FAIL", invalid.status)
        self.assertIn("fcff-v1", invalid.forbidden_models)

    def test_crypto_route_forbids_corporate_models(self):
        result = validate_model_route(
            EntityType.CRYPTO,
            (
                model("network-v1", "crypto_network"),
                model("pe-v1", "relative_pe"),
            ),
        )
        self.assertEqual("FAIL", result.status)
        self.assertIn("pe-v1", result.forbidden_models)

    def test_etf_route_uses_nav_not_pe(self):
        valid = validate_model_route(
            EntityType.ETF,
            (model("nav-v1", "etf_nav"),),
        )
        self.assertEqual("PASS", valid.status)
        invalid = validate_model_route(
            EntityType.ETF,
            (model("pe-v1", "relative_pe"),),
        )
        self.assertEqual("FAIL", invalid.status)


if __name__ == "__main__":
    unittest.main()
