import datetime as dt
import unittest

from packages.market_data.calendar import expected_bars, session_for_date
from packages.market_data.canonical import (
    canonical_checksum,
    canonicalize_crypto_4h,
    canonicalize_session,
    total_return,
)
from packages.market_data.models import CanonicalBar, RawPriceObservation, UTC
from packages.market_data.reconciliation import reconcile_bars


def observation(
    *,
    start,
    interval="15m",
    open_=100,
    high=101,
    low=99,
    close=100,
    adjusted=None,
    volume=10,
    run="run-a",
    provider="YAHOO",
    asset="STOCK",
    exchange="XNYS",
):
    seconds = {"15m": 900, "1d": 86400, "1h": 3600}[interval]
    return RawPriceObservation(
        provider=provider,
        provider_symbol="AAPL" if asset != "CRYPTO" else "BTC-USD",
        ticker="AAPL" if asset != "CRYPTO" else "BTC-USD",
        asset_type=asset,
        exchange=exchange,
        source_interval=interval,
        source_timezone="UTC",
        bar_start=start,
        bar_end=start + dt.timedelta(seconds=seconds),
        open=open_,
        high=high,
        low=low,
        close=close,
        adjusted_close=adjusted,
        volume=volume,
        currency="USD",
        available_at=start + dt.timedelta(seconds=seconds),
        ingested_at=start + dt.timedelta(seconds=seconds + 1),
        ingestion_run_id=run,
        source_version="test-v1",
        payload={"o": open_, "h": high, "l": low, "c": close, "v": volume},
    )


class MarketDataCoreTests(unittest.TestCase):
    def test_content_addressed_ids_are_stable_and_revision_sensitive(self):
        start = dt.datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
        first = observation(start=start, run="run-1")
        same = observation(start=start, run="run-2")
        changed = observation(start=start, close=101, high=102, run="run-3")
        self.assertEqual(first.raw_record_id, same.raw_record_id)
        self.assertEqual(first.raw_revision_id, same.raw_revision_id)
        self.assertNotEqual(first.raw_revision_id, changed.raw_revision_id)

    def test_observation_cannot_be_available_before_bar_close(self):
        start = dt.datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "available_at"):
            RawPriceObservation(
                provider="Y",
                provider_symbol="AAPL",
                ticker="AAPL",
                asset_type="STOCK",
                exchange="XNYS",
                source_interval="15m",
                source_timezone="UTC",
                bar_start=start,
                bar_end=start + dt.timedelta(minutes=15),
                open=100,
                high=101,
                low=99,
                close=100,
                adjusted_close=100,
                volume=1,
                currency="USD",
                available_at=start,
                ingested_at=start + dt.timedelta(minutes=16),
                ingestion_run_id="r",
                source_version="v",
                payload={},
            )

    def test_xnys_dst_changes_utc_open(self):
        before = session_for_date(dt.date(2026, 3, 6))
        after = session_for_date(dt.date(2026, 3, 9))
        self.assertEqual((14, 30), (before.open_utc.hour, before.open_utc.minute))
        self.assertEqual((13, 30), (after.open_utc.hour, after.open_utc.minute))

    def test_xnys_holiday_is_closed(self):
        self.assertIsNone(session_for_date(dt.date(2026, 7, 3)))

    def test_daily_and_intraday_never_mix(self):
        session = session_for_date(dt.date(2026, 8, 13))
        rows = []
        for index in range(expected_bars(session, "15m")):
            start = session.open_utc + dt.timedelta(minutes=15 * index)
            rows.append(
                observation(
                    start=start,
                    open_=100 + index / 100,
                    high=101 + index / 100,
                    low=99 + index / 100,
                    close=100.5 + index / 100,
                    volume=10,
                )
            )
        rows.append(
            observation(
                start=dt.datetime(2026, 8, 13, tzinfo=UTC),
                interval="1d",
                open_=95,
                high=110,
                low=90,
                close=105,
                adjusted=104,
                volume=9999,
            )
        )
        bar = canonicalize_session(rows, session)
        self.assertEqual("INTRADAY_COMPLETE", bar.selected_by_rule)
        self.assertEqual("15m", bar.source_interval)
        self.assertNotEqual(9999, bar.raw_volume)
        self.assertEqual(expected_bars(session, "15m") * 10, bar.raw_volume)

    def test_incomplete_intraday_falls_back_to_daily(self):
        session = session_for_date(dt.date(2026, 8, 13))
        rows = [
            observation(start=session.open_utc),
            observation(
                start=dt.datetime(2026, 8, 13, tzinfo=UTC),
                interval="1d",
                open_=98,
                high=103,
                low=97,
                close=102,
                adjusted=101,
                volume=500,
            ),
        ]
        bar = canonicalize_session(rows, session)
        self.assertEqual(
            "DAILY_FALLBACK_INCOMPLETE_INTRADAY",
            bar.selected_by_rule,
        )
        self.assertEqual(102, bar.raw_close)
        self.assertEqual(101, bar.adjusted_close)

    def test_split_and_dividend_total_return_continuity(self):
        self.assertAlmostEqual(0.0, total_return(100, 50, split_ratio=2), places=12)
        self.assertAlmostEqual(0.0, total_return(100, 99, dividend=1), places=12)

    def test_crypto_4h_requires_four_complete_hourly_bars(self):
        start = dt.datetime(2026, 8, 13, 0, 0, tzinfo=UTC)
        complete = [
            observation(
                start=start + dt.timedelta(hours=index),
                interval="1h",
                asset="CRYPTO",
                exchange="CRYPTO_24_7",
                open_=100 + index,
                high=101 + index,
                low=99 + index,
                close=100.5 + index,
            )
            for index in range(4)
        ]
        bars = canonicalize_crypto_4h(complete)
        self.assertEqual(1, len(bars))
        self.assertEqual("4h", bars[0].canonical_interval)
        self.assertEqual("CRYPTO_4H_COMPLETE", bars[0].selected_by_rule)
        self.assertEqual(0, len(canonicalize_crypto_4h(complete[:3])))

    def _bar(self, provider, close, volume=100, available_offset=0):
        start = dt.datetime(2026, 8, 13, 13, 30, tzinfo=UTC)
        return CanonicalBar(
            ticker="AAPL",
            asset_type="STOCK",
            exchange="XNYS",
            session_date=dt.date(2026, 8, 13),
            bar_start=start,
            bar_end=start + dt.timedelta(hours=6, minutes=30),
            canonical_interval="1d",
            raw_open=100,
            raw_high=max(101, close),
            raw_low=99,
            raw_close=close,
            adjusted_close=close,
            raw_volume=volume,
            currency="USD",
            provider=provider,
            source_interval="1d",
            coverage_ratio=1.0,
            quality_status="CANONICAL_RECONCILED",
            selected_by_rule="DAILY_FALLBACK_NO_INTRADAY",
            available_at=start + dt.timedelta(hours=7, seconds=available_offset),
            source_revision_ids=(provider,),
        )

    def test_provider_reconciliation_blocks_material_mismatch(self):
        result = reconcile_bars(
            self._bar("YAHOO", 100),
            self._bar("STOOQ", 102),
            close_tolerance_bps=10,
        )
        self.assertEqual("MATERIAL_MISMATCH", result.status)
        self.assertTrue(result.blocks_quality)

    def test_provider_reconciliation_accepts_small_difference(self):
        result = reconcile_bars(
            self._bar("YAHOO", 100),
            self._bar("STOOQ", 100.05),
            close_tolerance_bps=10,
        )
        self.assertEqual("WITHIN_TOLERANCE", result.status)
        self.assertFalse(result.blocks_quality)

    def test_missing_secondary_blocks_quality(self):
        result = reconcile_bars(self._bar("YAHOO", 100), None)
        self.assertEqual("SOURCE_MISSING", result.status)
        self.assertTrue(result.blocks_quality)

    def test_canonical_checksum_is_order_independent(self):
        first = self._bar("YAHOO", 100)
        second = CanonicalBar(
            **{
                **first.__dict__,
                "ticker": "MSFT",
                "source_revision_ids": ("MSFT",),
            }
        )
        self.assertEqual(
            canonical_checksum([first, second]),
            canonical_checksum([second, first]),
        )


if __name__ == "__main__":
    unittest.main()
