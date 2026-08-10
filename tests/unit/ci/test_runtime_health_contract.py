import importlib.util
import json
import os
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
CONTEXTS = (
    ("daily_stocks", "stockdaily"),
    ("financial_data", "stockfinancial"),
    ("macro_data", "stockmacrodata"),
    ("daily_ai_analysis", "stockaianalysis"),
    ("paper_trading_alerts", "papertradingalerts"),
    ("paper_trade_executor", "papertradeexecutor"),
    ("paper_trade_risk_monitor", "papertraderiskmonitor"),
    ("strategy_brain", "strategybrain"),
)


class Request:
    def __init__(self, path, method="GET"):
        self.path = path
        self.method = method


def load_runtime(context):
    path = ROOT / "cloud-functions" / context / "runtime_health.py"
    spec = importlib.util.spec_from_file_location(f"runtime_health_{context}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeHealthContractTests(unittest.TestCase):
    def test_every_service_has_static_liveness_and_real_readiness(self):
        environment = {
            "RELEASE_GIT_SHA": "a" * 40,
            "RELEASE_VERSION": "release-a",
            "RELEASE_IMAGE_DIGEST": "sha256:" + "b" * 64,
            "PROJECT_ID": "test-project",
            "project_id": "test-project",
            "dataset_id": "acciones_dataset",
            "bucket_name": "test-bucket",
            "table_id": "prices",
            "OPENAI_API_KEY": "placeholder",
            "ALERT_WEBHOOK_URL": "https://example.invalid/webhook",
            "ALPACA_API_KEY": "placeholder",
            "ALPACA_SECRET_KEY": "placeholder",
            "ALPACA_BASE_URL": "https://paper-api.alpaca.markets",
            "PAPER_EXECUTION_MODE": "paper",
            "BRAIN_EXECUTION_MODE": "BACKTEST_ONLY",
            "READINESS_TEST_MODE": "true",
            "READINESS_FAKE_TABLES": "*",
            "READINESS_FAKE_IMPORTS": "*",
        }
        with mock.patch.dict(os.environ, environment, clear=True):
            for context, service in CONTEXTS:
                module = load_runtime(context)
                for path in ("/healthz", "/readyz"):
                    with self.subTest(context=context, path=path):
                        body, status, headers = module.health_response(
                            Request(path), service
                        )
                        payload = json.loads(body)
                        self.assertEqual(status, 200)
                        self.assertEqual(headers["Cache-Control"], "no-store")
                        self.assertEqual(payload["service"], service)
                        self.assertEqual(payload["operation"], "readiness_probe")
                        self.assertFalse(payload["mutation_performed"])
                        if path == "/readyz":
                            self.assertTrue(payload["checks"])

    def test_missing_required_configuration_is_not_ready_but_health_is_live(self):
        module = load_runtime("daily_stocks")
        with mock.patch.dict(os.environ, {}, clear=True):
            health_body, health_status, _ = module.health_response(
                Request("/healthz"), "stockdaily"
            )
            ready_body, ready_status, _ = module.health_response(
                Request("/readyz"), "stockdaily"
            )
        self.assertEqual(health_status, 200)
        self.assertEqual(json.loads(health_body)["status"], "alive")
        self.assertEqual(ready_status, 503)
        self.assertEqual(json.loads(ready_body)["status"], "not_ready")

    def test_live_alpaca_or_non_paper_mode_is_never_ready(self):
        module = load_runtime("paper_trade_executor")
        base = {
            "RELEASE_GIT_SHA": "a" * 40,
            "RELEASE_VERSION": "release-a",
            "RELEASE_IMAGE_DIGEST": "sha256:" + "b" * 64,
            "PROJECT_ID": "test",
            "project_id": "test",
            "dataset_id": "dataset",
            "ALPACA_API_KEY": "placeholder",
            "ALPACA_SECRET_KEY": "placeholder",
            "READINESS_TEST_MODE": "true",
            "READINESS_FAKE_TABLES": "*",
            "READINESS_FAKE_IMPORTS": "*",
        }
        for mode, url in (
            ("live", "https://paper-api.alpaca.markets"),
            ("paper", "https://api.alpaca.markets"),
        ):
            with self.subTest(mode=mode, url=url):
                with mock.patch.dict(
                    os.environ,
                    {**base, "PAPER_EXECUTION_MODE": mode, "ALPACA_BASE_URL": url},
                    clear=True,
                ):
                    _, status, _ = module.health_response(
                        Request("/readyz"), "papertradeexecutor"
                    )
                self.assertEqual(status, 503)

    def test_health_post_is_rejected_without_mutation(self):
        module = load_runtime("daily_stocks")
        body, status, _ = module.health_response(Request("/healthz", "POST"), "stockdaily")
        self.assertEqual(status, 405)
        self.assertFalse(json.loads(body)["mutation_performed"])

    def test_business_path_is_not_intercepted(self):
        module = load_runtime("daily_stocks")
        self.assertIsNone(module.health_response(Request("/"), "stockdaily"))


if __name__ == "__main__":
    unittest.main()
