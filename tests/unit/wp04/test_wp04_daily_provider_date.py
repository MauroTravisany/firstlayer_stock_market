import datetime as dt
import unittest
from zoneinfo import ZoneInfo

from tools import wp04_primary_source_quality as quality


UTC = dt.timezone.utc
LONDON = ZoneInfo("Europe/London")


class FakeIndex:
    def __init__(self, timezone):
        self.tz = timezone


class FakeFrame:
    def __init__(self, rows, timezone):
        self.index = FakeIndex(timezone)
        self._rows = rows

    def iterrows(self):
        yield from self._rows


def row():
    return {
        "Open": 900,
        "High": 902,
        "Low": 898,
        "Close": 901,
        "Adj Close": 901,
        "Volume": 1000,
    }


def normalizer(payload, **kwargs):
    return {
        "raw_revision_id": f"{kwargs['ticker']}:{payload['timestamp'].isoformat()}",
        "event_time": payload["timestamp"],
    }


class Wp04DailyProviderDateTests(unittest.TestCase):
    def normalize_rows(self, timestamps, *, interval="1d"):
        return quality.normalize_yahoo_frame(
            FakeFrame([(timestamp, row()) for timestamp in timestamps], LONDON),
            provider_symbol="CLP=X",
            ticker="CLP=X",
            asset_type="FX",
            exchange="FX_24_5",
            source_interval=interval,
            currency="CLP",
            ingestion_run_id="run-test",
            source_version="test",
            ingested_at=dt.datetime(2026, 8, 20, tzinfo=UTC),
            normalizer=normalizer,
        )

    def normalize(self, timestamp, *, interval="1d"):
        return self.normalize_rows([timestamp], interval=interval)

    def test_monday_daily_fx_remains_monday_in_gmt_and_bst(self):
        for timestamp in (
            dt.datetime(2024, 1, 8, 0, 0, tzinfo=LONDON),
            dt.datetime(2024, 7, 8, 0, 0, tzinfo=LONDON),
        ):
            with self.subTest(timestamp=timestamp):
                accepted, status, rejected = self.normalize(timestamp)
                self.assertEqual(1, len(accepted))
                self.assertEqual([], rejected)
                self.assertEqual(0, status["off_session_row_count"])
                self.assertEqual(timestamp.date(), accepted[0]["event_time"].date())

    def test_weekends_and_fx_holidays_are_off_session(self):
        dates = (
            dt.date(2024, 1, 6),
            dt.date(2024, 1, 7),
            dt.date(2024, 1, 1),
            dt.date(2024, 12, 25),
            dt.date(2021, 12, 31),
            dt.date(2022, 12, 26),
        )
        for day in dates:
            with self.subTest(day=day):
                accepted, status, rejected = self.normalize_rows(
                    [
                        dt.datetime.combine(day, dt.time.min, tzinfo=LONDON),
                        dt.datetime(2024, 1, 2, 0, 0, tzinfo=LONDON),
                    ]
                )
                self.assertEqual(1, len(accepted))
                self.assertEqual(1, status["off_session_row_count"])
                self.assertEqual("OUTSIDE_CANONICAL_SESSION", rejected[0]["reason_code"])

    def test_daily_uses_provider_date_while_intraday_uses_session_bounds(self):
        timestamp = dt.datetime(2025, 5, 5, 0, 30, tzinfo=LONDON)
        accepted, _, rejected = self.normalize(timestamp, interval="1d")
        self.assertEqual(1, len(accepted))
        self.assertEqual([], rejected)

        accepted, status, rejected = self.normalize_rows(
            [timestamp, dt.datetime(2025, 5, 5, 2, 0, tzinfo=LONDON)],
            interval="15m",
        )
        self.assertEqual(1, len(accepted))
        self.assertEqual(1, status["off_session_row_count"])
        self.assertEqual("OUTSIDE_CANONICAL_SESSION", rejected[0]["reason_code"])

    def test_may_first_is_not_shifted_to_april_thirtieth(self):
        timestamp = dt.datetime(2025, 5, 1, 0, 0, tzinfo=LONDON)
        accepted, _, rejected = self.normalize(timestamp)
        self.assertEqual(1, len(accepted))
        self.assertEqual([], rejected)
        self.assertEqual(dt.date(2025, 5, 1), accepted[0]["event_time"].date())


if __name__ == "__main__":
    unittest.main()
