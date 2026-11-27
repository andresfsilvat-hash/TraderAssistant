"""Tests for cached 1-minute analysis; no credentials, network or orders."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import threading
import time
import unittest
import sys

from flask import Flask
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from analysis_live import (LiveAnalysisService, MIN_ROWS, compute_live_analysis,
                           official_candles_to_dataframe, register_live_analysis)
from screener.scorer import score_tickers


def candles(count=80, symbol_offset=0.0):
    base = int(datetime(2026, 11, 18, 14, 0, tzinfo=timezone.utc).timestamp())
    result = []
    for index in range(count):
        opened = 100 + symbol_offset + index * 0.03 + math.sin(index / 4) * 0.2
        closed = opened + math.sin(index / 3) * 0.12
        result.append({"time": base + index * 60, "open": opened,
                       "high": max(opened, closed) + 0.2,
                       "low": min(opened, closed) - 0.2,
                       "close": closed, "volume": 1000 + index,
                       "provisional": False})
    return result


def official_map(items):
    return {item["time"]: {k: item[k] for k in ("time", "open", "high", "low", "close", "volume")}
            for item in items}


class FakeFeed:
    def __init__(self, symbol="NVDA", items=None):
        self.lock = threading.RLock()
        self.symbol = symbol
        self.official = official_map(items or [])
        self.series_revision = 0
        self.history_source = "alpaca"


def wait_for(predicate, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


class AnalysisTests(unittest.TestCase):
    def test_ohlcv_conversion_excludes_provisional_sorts_and_replaces_duplicate(self):
        items = candles(5)
        duplicate = dict(items[2], close=items[2]["close"] + 0.1,
                         high=items[2]["high"] + 0.1, volume=9999)
        provisional = dict(items[4], time=items[4]["time"] + 60, provisional=True)
        invalid = dict(items[0], time=items[0]["time"] + 1200, high=1)
        frame, meta = official_candles_to_dataframe(
            [items[4], items[0], items[2], items[1], duplicate, items[3], provisional, invalid]
        )
        self.assertEqual(list(frame.columns), ["Open", "High", "Low", "Close", "Volume"])
        self.assertTrue(frame.index.is_monotonic_increasing)
        self.assertTrue(frame.index.is_unique)
        self.assertEqual(len(frame), 5)
        self.assertEqual(float(frame.iloc[2]["Volume"]), 9999)
        self.assertEqual(meta["duplicates_replaced"], 1)
        self.assertEqual(meta["provisional_excluded"], 1)
        self.assertEqual(meta["rejected"], 1)

    def test_rsi_and_macd_match_independent_pandas_reference(self):
        items = candles(100)
        result = compute_live_analysis({"symbol": "NVDA", "source": "alpaca", "candles": items,
                                        "feed_revision": 7})
        close = pd.Series([item["close"] for item in items], dtype=float)
        delta = close.diff()
        up = delta.where(delta > 0, 0.0)
        down = -delta.where(delta < 0, 0.0)
        avg_up = up.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        avg_down = down.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
        rsi_ref = 100 - 100 / (1 + avg_up / avg_down)
        fast = close.ewm(span=12, min_periods=12, adjust=False).mean()
        slow = close.ewm(span=26, min_periods=26, adjust=False).mean()
        macd = fast - slow
        macd_signal = macd.ewm(span=9, min_periods=9, adjust=False).mean()
        self.assertAlmostEqual(result["values"]["rsi_14"], float(rsi_ref.iloc[-1]), places=5)
        self.assertAlmostEqual(result["values"]["macd_12_26"], float(macd.iloc[-1]), places=5)
        self.assertAlmostEqual(result["values"]["macd_signal_9"], float(macd_signal.iloc[-1]), places=5)
        self.assertAlmostEqual(result["values"]["macd_histogram"],
                               float((macd - macd_signal).iloc[-1]), places=5)

    def test_original_pattern_detector_is_reused_and_ols_is_not_used(self):
        items = candles(60)
        items[-1].update(open=100, close=101, high=101.5, low=97, volume=2000)
        result = compute_live_analysis({"symbol": "NVDA", "source": "alpaca", "candles": items})
        self.assertTrue(any("Hammer" in item for item in result["patterns"]))
        self.assertFalse(any("OLS" in item for item in result["signals"]))
        self.assertEqual(result["decision"], "ESPERAR")
        self.assertIsNone(result["operational_signal"])

    def test_insufficient_history_is_explicit(self):
        result = compute_live_analysis({"symbol": "NVDA", "candles": candles(MIN_ROWS - 1)})
        self.assertEqual(result["status"], "insufficient")
        self.assertEqual(result["bias"], "Datos insuficientes")
        self.assertEqual(result["row_count"], MIN_ROWS - 1)

    def test_new_bar_and_historical_correction_recalculate_once(self):
        feed = FakeFeed(items=candles(60))
        service = LiveAnalysisService(feed, executor_factory=lambda: ThreadPoolExecutor(max_workers=1),
                                      poll_interval=0.01)
        service.start()
        try:
            self.assertTrue(wait_for(lambda: service.snapshot()["status"] == "ready"))
            first_count = service.snapshot()["service"]["calculation_count"]
            time.sleep(0.15)
            self.assertEqual(service.snapshot()["service"]["calculation_count"], first_count)
            with feed.lock:
                key = sorted(feed.official)[-10]
                feed.official[key]["close"] += 0.05
                feed.official[key]["high"] = max(feed.official[key]["high"], feed.official[key]["close"])
                feed.series_revision += 1
            self.assertTrue(wait_for(lambda: service.snapshot()["service"]["calculation_count"] == first_count + 1))
            time.sleep(0.15)
            self.assertEqual(service.snapshot()["service"]["calculation_count"], first_count + 1)
        finally:
            service.stop()

    def test_symbol_change_discards_previous_result(self):
        feed = FakeFeed(items=candles(60))

        def slow(payload):
            time.sleep(0.12)
            return compute_live_analysis(payload)

        service = LiveAnalysisService(feed, executor_factory=lambda: ThreadPoolExecutor(max_workers=1),
                                      analyzer=slow, poll_interval=0.01)
        service.start()
        try:
            self.assertTrue(wait_for(lambda: service.snapshot()["service"]["worker_busy"]))
            with feed.lock:
                feed.symbol = "AAPL"
                feed.official = official_map(candles(60, symbol_offset=50))
                feed.series_revision += 1
            self.assertTrue(wait_for(lambda: service.snapshot().get("symbol") == "AAPL" and
                                    service.snapshot().get("status") == "ready", timeout=6))
            snapshot = service.snapshot()
            self.assertEqual(snapshot["symbol"], "AAPL")
            self.assertGreaterEqual(snapshot["service"]["discarded_result_count"], 1)
        finally:
            service.stop()

    def test_analyzer_error_does_not_escape_or_affect_feed(self):
        feed = FakeFeed(items=candles(60))

        def broken(_payload):
            raise RuntimeError("controlled test")

        service = LiveAnalysisService(feed, executor_factory=lambda: ThreadPoolExecutor(max_workers=1),
                                      analyzer=broken, poll_interval=0.01)
        service.start()
        try:
            self.assertTrue(wait_for(lambda: service.snapshot()["status"] == "error"))
            self.assertEqual(len(feed.official), 60)
            self.assertEqual(service.snapshot()["analyzer_error"], "RuntimeError")
        finally:
            service.stop()

    def test_endpoint_returns_cached_result_without_calculation(self):
        feed = FakeFeed(items=[])
        app = Flask("analysis-test")
        service = register_live_analysis(app, feed=feed, start=False)
        service.current_symbol = "NVDA"
        service.state = compute_live_analysis({"symbol": "NVDA", "candles": candles(60)})
        before = service.calculation_count
        client = app.test_client()
        for _ in range(20):
            response = client.get("/api/analysis/live")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.get_json()["decision"], "ESPERAR")
        self.assertEqual(service.calculation_count, before)

    def test_cached_snapshot_refreshes_staleness_without_recalculation(self):
        feed = FakeFeed(items=[])
        service = LiveAnalysisService(feed, executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
        service.current_symbol = "NVDA"
        service.state = compute_live_analysis({"symbol": "NVDA", "candles": candles(60)})
        service.state["last_candle_time"] = datetime.fromtimestamp(
            time.time() - 400, tz=timezone.utc).isoformat()
        service.state["stale"] = False
        before = service.calculation_count
        result = service.snapshot()
        self.assertTrue(result["stale"])
        self.assertGreaterEqual(result["age_seconds"], 339)
        self.assertEqual(service.calculation_count, before)

    def test_calculation_of_500_bars_is_below_one_second(self):
        started = time.perf_counter()
        result = compute_live_analysis({"symbol": "SPY", "candles": candles(500)})
        elapsed = time.perf_counter() - started
        self.assertEqual(result["status"], "ready")
        self.assertLess(elapsed, 1.0)
        self.assertLess(result["calculation_ms"], 1000)

    def test_realtime_and_historical_engine_files_remain_unchanged(self):
        expected = {
            "alpaca_live.py": "C72BAB8D2A27C1C048D36593FED49C149BB41381F0A7E12F5B722E6A43CA3FCB",
            "main.py": "67CD9EC723DAAB05E1B498FD765F46763FCA90E320C6D1AE99F7CC9AC08BE2DC",
            "screener/indicator_detector.py": "5CCBB66A3E5CFF85B08941C5E241CC0B6717990042F4A09B299694706C3CC7E0",
            "screener/pattern_detector.py": "B10B67AB5DFEEDADD0DF1F73F19235182C7AFFD546D1981234895868FD894546",
            "screener/scorer.py": "99AE7B48DE29D6B5DF0CC2CEB4E2710655983518F139DDF335A331D82D142190",
            "screener/data_fetcher.py": "B8B428C6C9558FB8C4BA15B95C2B36213C79F2388D7B737989514B9C053E238C",
        }
        for relative, digest in expected.items():
            actual = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest().upper()
            self.assertEqual(actual, digest, relative)

    def test_original_historical_scorer_still_operates_with_daily_and_hourly_inputs(self):
        frame, _ = official_candles_to_dataframe(candles(80))
        ranked = score_tickers(
            {"NVDA": ["Hammer (1h)"]},
            {"NVDA": ["RSI oversold <30 (daily)  [RSI=25.0]"]},
            {"NVDA": frame}, {"NVDA": frame},
        )
        self.assertEqual(ranked["long"][0]["ticker"], "NVDA")
        self.assertGreater(ranked["long"][0]["score"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
