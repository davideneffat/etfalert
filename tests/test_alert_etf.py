import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.modules.setdefault("requests", MagicMock())
sys.modules.setdefault("yfinance", MagicMock())

from alert_etf import (
    Config,
    PriceSnapshot,
    evaluate_ticker,
    load_state,
    normalize_ticker_state,
    run,
    save_state,
)


def snapshot(price=95.0, high=100.0, date="2026-09-10"):
    return PriceSnapshot(price, date, high, "2026-08-01", "EUR")


class CascadeTests(unittest.TestCase):
    def test_first_run_initializes_without_alert(self):
        state, message = evaluate_ticker("ETF.MI", {}, snapshot(), 0.05)
        self.assertEqual(state["reference_price"], 100.0)
        self.assertIsNone(message)

    def test_exact_threshold_alerts_and_moves_reference(self):
        state, message = evaluate_ticker(
            "ETF.MI",
            {"reference_price": 100, "peak_price": 100, "alert_count": 0},
            snapshot(),
            0.05,
        )
        self.assertIsNotNone(message)
        self.assertEqual(state["reference_price"], 95.0)
        self.assertEqual(state["alert_count"], 1)

    def test_same_quote_does_not_duplicate_alert(self):
        old = {
            "reference_price": 100,
            "peak_price": 100,
            "alert_count": 1,
            "last_alert_quote_date": "2026-09-10",
        }
        state, message = evaluate_ticker("ETF.MI", old, snapshot(price=90), 0.05)
        self.assertIsNone(message)
        self.assertEqual(state["reference_price"], 100.0)

    def test_new_high_resets_cascade(self):
        old = {"reference_price": 90, "peak_price": 100, "alert_count": 2}
        state, message = evaluate_ticker(
            "ETF.MI", old, snapshot(price=101, high=101), 0.05
        )
        self.assertEqual(state["reference_price"], 101)
        self.assertEqual(state["alert_count"], 0)
        self.assertIsNone(message)

    def test_old_state_without_peak_is_migrated(self):
        state = normalize_ticker_state({"reference_price": 90, "alert_count": 1})
        self.assertEqual(state["peak_price"], 90)

    def test_invalid_state_is_rejected(self):
        with self.assertRaises(ValueError):
            normalize_ticker_state({"reference_price": -1})


class PersistenceTests(unittest.TestCase):
    def test_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_state(path, {"ETF.MI": {"reference_price": 10}})
            self.assertEqual(load_state(path)["ETF.MI"]["reference_price"], 10)
            json.loads(path.read_text())

    def test_dry_run_does_not_write_or_send(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            original = {
                "ETF.MI": {
                    "reference_price": 100,
                    "peak_price": 100,
                    "alert_count": 0,
                }
            }
            path.write_text(json.dumps(original))
            config = Config(("ETF.MI",), 0.05, 365, 7, path, None, None, True)
            with patch("alert_etf.send_telegram_message") as sender:
                result = run(config, lambda *_: snapshot())
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(path.read_text()), original)
            sender.assert_not_called()

    def test_failed_ticker_keeps_state_and_other_ticker_progresses(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            original = {
                "BAD": {
                    "reference_price": 10,
                    "peak_price": 10,
                    "alert_count": 0,
                }
            }
            path.write_text(json.dumps(original))
            config = Config(("BAD", "GOOD"), 0.05, 365, 7, path, "token", "chat")

            def fetcher(ticker, *_):
                if ticker == "BAD":
                    raise RuntimeError("rete")
                return snapshot()

            self.assertEqual(run(config, fetcher), 1)
            saved = load_state(path)
            self.assertEqual(saved["BAD"], original["BAD"])
            self.assertIn("GOOD", saved)

    def test_telegram_failure_does_not_advance_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            original = {
                "ETF.MI": {
                    "reference_price": 100,
                    "peak_price": 100,
                    "alert_count": 0,
                }
            }
            path.write_text(json.dumps(original))
            config = Config(("ETF.MI",), 0.05, 365, 7, path, "token", "chat")
            with patch(
                "alert_etf.send_telegram_message", side_effect=RuntimeError("Telegram")
            ):
                self.assertEqual(run(config, lambda *_: snapshot()), 1)
            saved = load_state(path)
            self.assertEqual(saved["ETF.MI"], original["ETF.MI"])


if __name__ == "__main__":
    unittest.main()
