import datetime as dt
import math
from pathlib import Path
import unittest

from packages.market_data.calendar import fx_holidays, session_for_date
from tools import wp04_primary_source_quality as quality


UTC = dt.timezone.utc


class FakeIndex:
    tz = UTC


class FakeFrame:
    def __init__(self, rows):
        self.index = FakeIndex()
        self._rows = rows

    def iterrows(self):
        yield from self._rows


def row(open_, high, low, close, adjusted=None, volume=1000):
    return {
        "Open": open_,
        "High": high,
        "Low": low,
        "Close": close,
        "Adj Close": close if adjusted is None else adjusted,
        "Volume": volume,
    }


def normalizer(payload, **kwargs):
    return {
        "raw_revision_id": (
            f"{kwargs['ticker']}:{kwargs['source_interval']}:"
            f"{payload['timestamp'].isoformat()}"
        ),
        "ticker": kwargs["ticker"],
        "source_interval": kwargs["source_interval"],
    }


class Wp04PrimarySourceQualityTests(unittest.TestCase):
    def normalize(self, frame, **overrides):
        params = {
            "provider_symbol": "CLP=X",
            "ticker": "CLP=X",
            "asset_type": "FX",
            "exchange": "FX_24_5",
            "source_interval": "1d",
            "currency": "CLP",
            "ingestion_run_id": "run-test",
            "source_version": "yfinance-test",
            "ingested_at": dt.datetime(2026, 8, 20, tzinfo=UTC),
            "normalizer": normalizer,
        }
        params.update(overrides)
        return quality.normalize_yahoo_frame(frame, **params)

    def test_new_year_fx_row_is_quarantined_before_ohlc_validation(self):
        frame = FakeFrame(
            [
                (
                    dt.datetime(2024, 1, 1, tzinfo=UTC),
                    row(900, 899, 898, 900),
                ),
                (
                    dt.datetime(2024, 1, 2, tzinfo=UTC),
                    row(900, 902, 898, 901),
                ),
            ]
        )
        accepted, status, rejected = self.normalize(frame)
        self.assertEqual(1, len(accepted))
        self.assertEqual(1, len(rejected))
        self.assertEqual(
            "OUTSIDE_CANONICAL_SESSION",
            rejected[0]["reason_code"],
        )
        self.assertEqual(1, status["off_session_row_count"])
        self.assertEqual(0, status["invalid_row_count"])
        self.assertEqual("AVAILABLE_WITH_QUARANTINE", status["status"])
        self.assertFalse(status["production_change_allowed"])

    def test_one_in_session_bad_row_is_bounded_and_audited(self):
        rows = []
        day = dt.date(2024, 1, 2)
        while len(rows) < 201:
            if session_for_date(day, exchange="FX_24_5", asset_type="FX"):
                values = row(900, 902, 898, 901)
                if len(rows) == 50:
                    values = row(900, 899, 898, 900)
                rows.append(
                    (
                        dt.datetime.combine(day, dt.time.min, tzinfo=UTC),
                        values,
                    )
                )
            day += dt.timedelta(days=1)

        accepted, status, rejected = self.normalize(FakeFrame(rows))
        self.assertEqual(200, len(accepted))
        self.assertEqual(1, len(rejected))
        self.assertEqual("OHLC_INCONSISTENT", rejected[0]["reason_code"])
        self.assertEqual(1, status["invalid_row_count"])
        self.assertGreaterEqual(
            status["valid_row_ratio"],
            quality.MIN_VALID_ROW_RATIO,
        )

    def test_material_invalid_ratio_fails_closed(self):
        rows = []
        day = dt.date(2024, 1, 2)
        while len(rows) < 10:
            if session_for_date(day, exchange="FX_24_5", asset_type="FX"):
                values = row(900, 902, 898, 901)
                if len(rows) == 3:
                    values = row(900, 899, 898, 900)
                rows.append(
                    (
                        dt.datetime.combine(day, dt.time.min, tzinfo=UTC),
                        values,
                    )
                )
            day += dt.timedelta(days=1)

        with self.assertRaisesRegex(
            quality.PrimarySourceQualityError,
            "valid-row ratio is below policy",
        ):
            self.normalize(FakeFrame(rows))

    def test_missing_optional_values_remain_null_without_price_repair(self):
        cleaned = quality.clean_price_payload(
            {
                "timestamp": dt.datetime(2024, 1, 2, tzinfo=UTC),
                "open": 900,
                "high": 902,
                "low": 898,
                "close": 901,
                "adjusted_close": math.nan,
                "volume": math.nan,
            }
        )
        self.assertIsNone(cleaned["adjusted_close"])
        self.assertIsNone(cleaned["volume"])
        self.assertEqual(900.0, cleaned["open"])
        self.assertEqual(902.0, cleaned["high"])
        self.assertEqual(898.0, cleaned["low"])
        self.assertEqual(901.0, cleaned["close"])

    def test_fx_calendar_closes_new_year_and_observed_new_year(self):
        self.assertIn(dt.date(2024, 1, 1), fx_holidays(2024))
        self.assertIsNone(
            session_for_date(
                dt.date(2024, 1, 1),
                exchange="FX_24_5",
                asset_type="FX",
            )
        )
        self.assertIn(dt.date(2021, 12, 31), fx_holidays(2021))
        self.assertIsNotNone(
            session_for_date(
                dt.date(2024, 1, 2),
                exchange="FX_24_5",
                asset_type="FX",
            )
        )

    def test_rejection_artifact_contains_no_raw_ohlc_values(self):
        frame = FakeFrame(
            [
                (
                    dt.datetime(2024, 1, 1, tzinfo=UTC),
                    row(987654, 900, 800, 987654),
                ),
                (
                    dt.datetime(2024, 1, 2, tzinfo=UTC),
                    row(900, 902, 898, 901),
                ),
            ]
        )
        _accepted, _status, rejected = self.normalize(frame)
        serialized = str(rejected[0])
        self.assertNotIn("987654", serialized)
        self.assertIn("payload_hash", rejected[0])
        self.assertRegex(rejected[0]["payload_hash"], r"^[0-9a-f]{64}$")


class Wp04PrimarySourceEntrypointTests(unittest.TestCase):
    def test_authorized_planner_uses_quarantine_facade(self):
        root = Path(__file__).resolve().parents[3]
        source = (
            root / "tools" / "wp04_shadow_backfill_windowed_official_fx.py"
        ).read_text(encoding="utf-8")
        self.assertIn("wp04_official_fx_planner", source)
        self.assertNotIn("wp04_resilient_planner", source)


if __name__ == "__main__":
    unittest.main()
