import datetime as dt
import unittest

from tools import wp04_provider_window as provider


UTC = dt.timezone.utc
EXPECTED_POLICY_VERSION = "wp04-yahoo-moving-window-v1"


class Wp04PolicyIdentifierTests(unittest.TestCase):
    def test_repository_and_generated_document_use_operator_contract(self):
        self.assertEqual(EXPECTED_POLICY_VERSION, provider.POLICY_VERSION)
        document = provider.resolve_provider_window(
            anchor_at=dt.datetime(2026, 8, 19, 12, tzinfo=UTC),
            intraday_lookback_days=30,
            hourly_lookback_days=365,
        )
        self.assertEqual(EXPECTED_POLICY_VERSION, document["policy_version"])
        self.assertEqual(
            document["window_checksum"],
            provider.verify_provider_window(document),
        )

    def test_any_other_policy_identifier_fails_closed(self):
        document = provider.resolve_provider_window(
            anchor_at=dt.datetime(2026, 8, 19, 12, tzinfo=UTC),
            intraday_lookback_days=30,
            hourly_lookback_days=365,
        )
        document["policy_version"] = "invalid-policy"
        with self.assertRaisesRegex(
            provider.ProviderWindowError,
            "expected wp04-yahoo-moving-window-v1",
        ):
            provider.verify_provider_window(document)


if __name__ == "__main__":
    unittest.main()
