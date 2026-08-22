import datetime as dt
import unittest

import requests

from tools import wp04_fx_source as source


UTC = dt.timezone.utc


class FakeResponse:
    def __init__(self, document=None, status_code=200, json_error=None):
        self._document = document
        self.status_code = status_code
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise self._json_error
        return self._document


def document(observations, code=0, series_id=source.SERIES_ID):
    return {
        "Codigo": code,
        "Descripcion": "Success" if code == 0 else "Failure",
        "Series": {"seriesId": series_id, "Obs": observations},
    }


def observation(day, value, status="OK"):
    return {
        "indexDateString": day.strftime("%d-%m-%Y"),
        "value": value,
        "statusCode": status,
    }


class Wp04BcchFxSourceTests(unittest.TestCase):
    def fetch(self, observations, **overrides):
        captured = {}

        def fake_get(*_args, **kwargs):
            captured.update(kwargs)
            return FakeResponse(document(observations))

        kwargs = {
            "token": "private-token-value",
            "start_date": dt.date(2024, 10, 7),
            "end_date": dt.date(2024, 10, 8),
            "ingestion_run_id": "run-test",
            "clock": lambda: dt.datetime(2024, 10, 9, 12, tzinfo=UTC),
            "get": fake_get,
        }
        kwargs.update(overrides)
        rows, status = source.fetch_bcch_observed_dollar(**kwargs)
        return rows, status, captured

    def test_official_rows_preserve_scalar_rate_and_publication_lineage(self):
        rows, status, captured = self.fetch(
            [
                observation(dt.date(2024, 10, 4), "897.68"),
                observation(dt.date(2024, 10, 7), "923,74"),
                observation(dt.date(2024, 10, 8), "924.10"),
                observation(dt.date(2024, 10, 6), "ND", "ND"),
            ]
        )
        self.assertEqual(2, len(rows))
        self.assertEqual("private-token-value", captured["params"]["token"])
        self.assertEqual(dt.date(2024, 9, 5), dt.date.fromisoformat(captured["params"]["firstdate"]))
        first = rows[0]
        self.assertEqual("BCCH_BDE", first["provider"])
        self.assertEqual("F073.TCO.PRE.Z.D", first["series_id"])
        self.assertEqual(dt.date(2024, 10, 4), first["source_reference_date"])
        self.assertEqual(dt.datetime(2024, 10, 4, 20, 30, tzinfo=UTC), first["source_published_at"])
        self.assertEqual(dt.datetime(2024, 10, 9, 12, tzinfo=UTC), first["available_at"])
        self.assertEqual(first["first_observed_at"], first["available_at"])
        self.assertEqual("CURRENT_SNAPSHOT_NO_VINTAGE", first["quality_status"])
        self.assertFalse(first["backtest_eligible"])
        self.assertEqual("API_KEY", status["authentication_mode"])
        self.assertEqual({"ND": 1}, status["skipped_status_counts"])
        serialized = str(rows) + str(status)
        self.assertNotIn("private-token-value", serialized)
        for forbidden in ("open", "high", "low", "close", "adjusted_close", "volume"):
            self.assertNotIn(forbidden, first)

    def test_santiago_publication_uses_dst_and_standard_offsets(self):
        summer, _, _ = self.fetch(
            [
                observation(dt.date(2024, 1, 4), "900"),
                observation(dt.date(2024, 1, 5), "901"),
            ],
            start_date=dt.date(2024, 1, 5),
            end_date=dt.date(2024, 1, 5),
            clock=lambda: dt.datetime(2024, 1, 6, tzinfo=UTC),
        )
        winter, _, _ = self.fetch(
            [
                observation(dt.date(2024, 6, 4), "900"),
                observation(dt.date(2024, 6, 5), "901"),
            ],
            start_date=dt.date(2024, 6, 5),
            end_date=dt.date(2024, 6, 5),
            clock=lambda: dt.datetime(2024, 6, 6, tzinfo=UTC),
        )
        self.assertEqual(20, summer[0]["source_published_at"].hour)
        self.assertEqual(21, winter[0]["source_published_at"].hour)

    def test_identity_is_stable_and_revision_changes_with_payload(self):
        base = [
            observation(dt.date(2024, 10, 4), "897.68"),
            observation(dt.date(2024, 10, 7), "923.74"),
        ]
        first, _, _ = self.fetch(base, ingestion_run_id="run-one")
        second, _, _ = self.fetch(base, ingestion_run_id="run-two")
        changed, _, _ = self.fetch(
            [base[0], observation(dt.date(2024, 10, 7), "923.75")],
            ingestion_run_id="run-three",
        )
        self.assertEqual(first[0]["fx_rate_record_id"], second[0]["fx_rate_record_id"])
        self.assertEqual(first[0]["fx_rate_revision_id"], second[0]["fx_rate_revision_id"])
        self.assertEqual(first[0]["fx_rate_record_id"], changed[0]["fx_rate_record_id"])
        self.assertNotEqual(first[0]["fx_rate_revision_id"], changed[0]["fx_rate_revision_id"])

    def test_missing_prior_ok_observation_fails_closed(self):
        with self.assertRaisesRegex(source.OfficialFxSourceError, "prior OK"):
            self.fetch(
                [observation(dt.date(2024, 10, 7), "923.74")],
                start_date=dt.date(2024, 10, 7),
                end_date=dt.date(2024, 10, 7),
            )

    def test_missing_token_fails_before_network_and_is_sanitized(self):
        with self.assertRaises(source.OfficialFxSourceError) as raised:
            source.fetch_bcch_observed_dollar(
                token=None,
                start_date=dt.date(2024, 1, 1),
                end_date=dt.date(2024, 1, 2),
                ingestion_run_id="run",
                clock=lambda: dt.datetime(2024, 1, 4, tzinfo=UTC),
                get=lambda *_a, **_k: self.fail("network called"),
            )
        self.assertEqual("AUTHENTICATION_MISSING", raised.exception.reason_code)

    def test_transport_and_api_failures_are_sanitized(self):
        cases = [
            (lambda *_a, **_k: FakeResponse(status_code=401), "AUTHENTICATION_FAILED"),
            (lambda *_a, **_k: FakeResponse(status_code=403), "AUTHENTICATION_FAILED"),
            (lambda *_a, **_k: FakeResponse(status_code=429), "RATE_LIMITED"),
            (lambda *_a, **_k: FakeResponse(json_error=ValueError("secret body")), "INVALID_JSON_RESPONSE"),
            (lambda *_a, **_k: FakeResponse(document([], code=5)), "API_NON_SUCCESS"),
            (lambda *_a, **_k: (_ for _ in ()).throw(requests.ConnectionError("private-token-value")), "NETWORK_ERROR"),
        ]
        for getter, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(source.OfficialFxSourceError) as raised:
                source.fetch_bcch_observed_dollar(
                    token="private-token-value",
                    start_date=dt.date(2024, 1, 1),
                    end_date=dt.date(2024, 1, 2),
                    ingestion_run_id="run",
                    clock=lambda: dt.datetime(2024, 1, 4, tzinfo=UTC),
                    get=getter,
                )
            self.assertEqual(reason, raised.exception.reason_code)
            self.assertNotIn("private-token-value", str(raised.exception))

    def test_observation_clock_runs_once_after_response_validation(self):
        events = []
        observed_at = dt.datetime(2026, 8, 22, 3, 2, tzinfo=UTC)

        class OrderedResponse(FakeResponse):
            def json(self):
                events.append("json_validated")
                return super().json()

        def fake_get(*_args, **_kwargs):
            events.append("http_received")
            return OrderedResponse(
                document(
                    [
                        observation(dt.date(2024, 10, 4), "897.68"),
                        observation(dt.date(2024, 10, 7), "923.74"),
                    ]
                )
            )

        def clock():
            events.append("clock_captured")
            return observed_at

        rows, status = source.fetch_bcch_observed_dollar(
            token="private-token-value",
            start_date=dt.date(2024, 10, 7),
            end_date=dt.date(2024, 10, 7),
            ingestion_run_id="run-clock",
            clock=clock,
            get=fake_get,
        )

        self.assertEqual(
            ["http_received", "json_validated", "clock_captured"], events
        )
        self.assertEqual(observed_at, rows[0]["first_observed_at"])
        self.assertEqual(observed_at, rows[0]["available_at"])
        self.assertEqual(observed_at, rows[0]["ingested_at"])
        self.assertEqual(observed_at, status["observed_at"])

    def test_duplicate_non_positive_and_non_finite_values_fail_closed(self):
        cases = [
            ([observation(dt.date(2024, 10, 4), "900"), observation(dt.date(2024, 10, 4), "901")], "DUPLICATE_OBSERVATION_DATE"),
            ([observation(dt.date(2024, 10, 4), "900"), observation(dt.date(2024, 10, 7), "0")], "INVALID_OBSERVATION_VALUE"),
            ([observation(dt.date(2024, 10, 4), "900"), observation(dt.date(2024, 10, 7), "Infinity")], "INVALID_OBSERVATION_VALUE"),
        ]
        for observations, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(source.OfficialFxSourceError) as raised:
                self.fetch(observations)
            self.assertEqual(reason, raised.exception.reason_code)

    def test_ok_nd_and_nan_values_are_skipped_without_becoming_rates(self):
        rows, status, _ = self.fetch(
            [
                observation(dt.date(2024, 10, 4), "900"),
                observation(dt.date(2024, 10, 5), "ND"),
                observation(dt.date(2024, 10, 6), "NaN"),
                observation(dt.date(2024, 10, 7), "923.74"),
            ],
            start_date=dt.date(2024, 10, 5),
            end_date=dt.date(2024, 10, 7),
        )
        self.assertEqual(1, len(rows))
        self.assertEqual({"NAN": 1, "ND": 1}, status["skipped_status_counts"])

    def test_invalid_date_missing_and_non_numeric_values_fail_closed(self):
        cases = [
            (
                [{"indexDateString": "2024/10/04", "value": "900", "statusCode": "OK"}],
                "INVALID_OBSERVATION_DATE",
            ),
            (
                [observation(dt.date(2024, 10, 4), "900"), observation(dt.date(2024, 10, 7), "")],
                "MISSING_OBSERVATION_VALUE",
            ),
            (
                [observation(dt.date(2024, 10, 4), "900"), observation(dt.date(2024, 10, 7), "not-a-rate")],
                "NON_NUMERIC_OBSERVATION",
            ),
        ]
        for observations, reason in cases:
            with self.subTest(reason=reason), self.assertRaises(source.OfficialFxSourceError) as raised:
                self.fetch(observations)
            self.assertEqual(reason, raised.exception.reason_code)


if __name__ == "__main__":
    unittest.main()
