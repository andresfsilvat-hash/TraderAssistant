"""Regression tests for the exact REALTIME backend installed at project root.

Set TRADERASSISTANT_REALTIME_BACKEND only while validating a staged payload.
No credentials, Internet access, orders, or project cache writes are used.
"""
from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BACKEND = Path(os.environ.get("TRADERASSISTANT_REALTIME_BACKEND", ROOT / "alpaca_live.py")).resolve()
source = BACKEND.read_text(encoding="utf-8").replace(
    "atexit.register(_feed._save_cache)", "# disabled by isolated audit tests"
)
backend = types.ModuleType("tested_active_realtime")
backend.__file__ = str(BACKEND)
exec(compile(source, str(BACKEND), "exec"), backend.__dict__)


def stamp(seconds):
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def trade(seconds, price, trade_id, symbol="NVDA", size=100, conditions=None):
    return {"T": "t", "S": symbol, "t": stamp(seconds), "p": price, "s": size,
            "c": ["@"] if conditions is None else conditions, "z": "C",
            "x": "V", "i": trade_id}


class FakeSocket:
    def __init__(self):
        self.sent = []

    def send(self, payload):
        self.sent.append(json.loads(payload))


class StreamSocket(FakeSocket):
    def __init__(self, batches):
        super().__init__()
        self.batches = batches

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def __iter__(self):
        for batch in self.batches:
            yield json.dumps(batch)


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._payload = payload

    def json(self):
        return self._payload


class RealtimeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        backend.CACHE_FILE = Path(self.temp.name) / "alpaca_iex_nvda.json"
        backend.STREAM_LOCK_FILE = Path(self.temp.name) / "stream.lock"
        self.feed = backend.LiveFeed()
        self.feed._process_lock = backend._ProcessStreamLock(backend.STREAM_LOCK_FILE)
        self.base = 1795008600

    def tearDown(self):
        self.feed._process_lock.release()
        self.temp.cleanup()

    def test_test_target_is_explicit_and_named_active_module(self):
        self.assertEqual(BACKEND.name, "alpaca_live.py")
        if os.environ.get("TRADERASSISTANT_REALTIME_BACKEND"):
            self.assertIn("payload", BACKEND.parts)
        else:
            self.assertEqual(BACKEND, (ROOT / "alpaca_live.py").resolve())

    def test_out_of_order_trades_preserve_event_time_open_close(self):
        self.feed.on_trade(trade(self.base + 8, 108, 1))
        self.feed.on_trade(trade(self.base + 2, 102, 2))
        self.feed.on_trade(trade(self.base + 5, 105, 3))
        candle = self.feed.provisional
        self.assertEqual(candle["open"], 102)
        self.assertEqual(candle["close"], 108)
        self.assertEqual(candle["high"], 108)
        self.assertEqual(candle["low"], 102)
        self.assertEqual(candle["volume"], 300)

    def test_late_five_second_bucket_is_inserted_sorted(self):
        self.feed.on_trade(trade(self.base + 12, 112, 10))
        self.feed.on_trade(trade(self.base + 2, 102, 11))
        self.feed.on_trade(trade(self.base + 7, 107, 12))
        self.assertEqual([b["time"] for b in self.feed.short_bars],
                         [self.base, self.base + 5, self.base + 10])
        self.assertGreaterEqual(self.feed.series_revision, 2)

    def test_excessively_late_five_second_trade_is_counted_not_inserted(self):
        self.feed.on_trade(trade(self.base + 100, 110, 20))
        self.feed.on_trade(trade(self.base + 1, 101, 21))
        self.assertEqual(len(self.feed.short_bars), 1)
        self.assertEqual(self.feed.late_trade_drop_count, 1)

    def test_duplicate_trade_does_not_duplicate_volume(self):
        item = trade(self.base + 1, 100, 30)
        self.feed.on_trade(item)
        self.feed.on_trade(item)
        self.assertEqual(self.feed.trade_count, 1)
        self.assertEqual(self.feed.provisional["volume"], 100)

    def test_official_bar_replaces_provisional_without_volume_merge(self):
        self.feed.on_trade(trade(self.base + 1, 100, 40))
        self.feed.insert_bar({"time": self.base, "open": 99, "high": 101,
                              "low": 98, "close": 100.5, "volume": 900})
        result = self.feed.snapshot()["candles"][-1]
        self.assertEqual(result["volume"], 900)
        self.assertEqual(result["quality"], "official")
        self.assertIsNone(self.feed.provisional)

    def test_late_trade_can_fill_recent_5s_bucket_without_touching_official_1m(self):
        self.feed.on_trade(trade(self.base + 62, 110, 41))
        official = {"time": self.base, "open": 99, "high": 101,
                    "low": 98, "close": 100.5, "volume": 900}
        self.feed.insert_bar(official)
        self.feed.on_trade(trade(self.base + 57, 105, 42))
        self.assertEqual(self.feed.official[self.base]["close"], 100.5)
        self.assertIn(self.base + 55, [b["time"] for b in self.feed.short_bars])

    def test_updated_official_bar_changes_revision(self):
        bar = {"time": self.base, "open": 99, "high": 101, "low": 98,
               "close": 100, "volume": 900}
        self.feed.insert_bar(bar)
        self.feed.insert_bar(dict(bar, close=100.5, volume=950))
        self.assertEqual(self.feed.official[self.base]["volume"], 950)
        self.assertGreaterEqual(self.feed.series_revision, 1)

    def test_quote_keeps_trade_separate_and_rejects_older_quote(self):
        self.feed.on_quote({"S": "NVDA", "t": stamp(self.base + 8), "bp": 100,
                            "ap": 102, "bs": 2, "as": 3})
        self.feed.on_quote({"S": "NVDA", "t": stamp(self.base + 2), "bp": 90,
                            "ap": 91, "bs": 2, "as": 3})
        self.assertEqual(self.feed.last_quote["mid"], 101)
        self.assertIsNone(self.feed.last_trade)

    def test_subscription_requires_all_four_channels(self):
        socket = FakeSocket()
        authenticated, fatal = self.feed._feed_message(
            {"T": "success", "msg": "authenticated"}, socket, False)
        self.assertTrue(authenticated)
        self.assertFalse(fatal)
        sent = socket.sent[-1]
        self.assertTrue(all(name in sent for name in backend.REQUIRED_CHANNELS))
        partial = {"T": "subscription", "trades": ["NVDA"], "bars": ["NVDA"],
                   "quotes": [], "updatedBars": []}
        self.feed._feed_message(partial, socket, True)
        self.assertEqual(self.feed.status, "suscripcion_incompleta")
        complete = {"T": "subscription", **{name: ["NVDA"] for name in backend.REQUIRED_CHANNELS}}
        self.feed._feed_message(complete, socket, True)
        self.assertEqual(self.feed.status, "conectado")

    def test_406_407_500_are_controlled_retry_errors(self):
        for code in (406, 407, 500):
            with self.subTest(code=code):
                _, retry = self.feed._feed_message({"T": "error", "code": code}, FakeSocket(), True)
                self.assertTrue(retry)
                self.assertEqual(self.feed.last_error_code, code)

    def test_run_records_controlled_reconnect_for_406_407_and_network_failure(self):
        class StopAudit(Exception):
            pass
        complete = {"T": "subscription", **{name: ["NVDA"] for name in backend.REQUIRED_CHANNELS}}
        for code in (406, 407):
            stream = StreamSocket([[{"T": "success", "msg": "authenticated"}],
                                   [complete], [{"T": "error", "code": code}]])
            local = backend.LiveFeed()
            with patch.object(backend, "_credentials", return_value=("fake", "fake")), \
                    patch.object(backend, "connect", return_value=stream), \
                    patch.object(local, "_start_history", return_value=False), \
                    patch.object(backend.time, "sleep", side_effect=StopAudit), \
                    patch.object(backend.random, "uniform", return_value=0):
                with self.assertRaises(StopAudit):
                    local.run()
            self.assertEqual(local.reconnect_count, 1)
            self.assertEqual(local.last_reconnect_reason, str(code))
        local = backend.LiveFeed()
        with patch.object(backend, "_credentials", return_value=("fake", "fake")), \
                patch.object(backend, "connect", side_effect=OSError("offline")), \
                patch.object(local, "_start_history", return_value=False), \
                patch.object(backend.time, "sleep", side_effect=StopAudit), \
                patch.object(backend.random, "uniform", return_value=0):
            with self.assertRaises(StopAudit):
                local.run()
        self.assertEqual(local.reconnect_count, 1)
        self.assertEqual(local.last_reconnect_reason, "OSError")

    def test_process_lock_excludes_second_owner(self):
        first = backend._ProcessStreamLock(backend.STREAM_LOCK_FILE)
        second = backend._ProcessStreamLock(backend.STREAM_LOCK_FILE)
        self.assertTrue(first.acquire())
        self.assertFalse(second.acquire())
        first.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_cache_round_trip_and_sources(self):
        self.feed.on_trade(trade(self.base + 1, 100, 50))
        self.feed.insert_bar({"time": self.base - 60, "open": 99, "high": 101,
                              "low": 98, "close": 100, "volume": 900})
        self.feed._save_cache()
        restored = backend.LiveFeed()
        self.assertEqual(len(restored.short_bars), 1)
        self.assertEqual(restored.short_bars[0]["origin"], "cache")
        self.assertEqual(restored.official[self.base - 60]["origin"], "cache")

    def test_read_only_second_instance_does_not_rewrite_cache(self):
        clean = backend.LiveFeed()
        path = clean._cache_file()
        self.assertFalse(clean._cache_dirty)
        clean._save_cache()
        self.assertFalse(path.exists())

    def test_old_symbol_events_cannot_contaminate_selected_symbol(self):
        with patch.object(self.feed, "_save_cache"), patch.object(backend, "_credentials",
                side_effect=OSError("test")):
            self.feed.select_symbol("AAPL")
        self.feed.on_trade(trade(self.base + 1, 100, 60, symbol="NVDA"))
        self.assertIsNone(self.feed.last_trade)
        self.feed.on_trade(trade(self.base + 2, 200, 61, symbol="AAPL"))
        self.assertEqual(self.feed.last_trade["price"], 200)

    def test_correction_requests_reconciliation(self):
        self.feed._feed_message({"T": "c", "S": "NVDA"}, FakeSocket(), True)
        self.assertTrue(self.feed._reconcile_requested)
        self.assertEqual(self.feed.correction_count, 1)

    def test_calendar_drives_premarket_regular_postmarket_and_holiday(self):
        calendar = [{"date": "2026-11-18", "open": "09:30", "close": "13:00",
                     "session_open": "0400", "session_close": "2000"}]
        cases = [("2026-11-18T08:00:00-05:00", False, "PREMARKET"),
                 ("2026-11-18T10:00:00-05:00", True, "REGULAR"),
                 ("2026-11-18T14:00:00-05:00", False, "POSTMARKET")]
        for provider_time, is_open, expected in cases:
            clock = {"timestamp": provider_time, "is_open": is_open,
                     "next_open": "2026-11-19T09:30:00-05:00",
                     "next_close": "2026-11-19T16:00:00-05:00"}
            with patch.object(backend.requests, "get", side_effect=[FakeResponse(payload=clock),
                                                                    FakeResponse(payload=calendar)]):
                self.feed._refresh_market_clock("fake", "fake")
            self.assertEqual(self.feed.market_clock["phase"], expected)
        holiday_clock = {"timestamp": "2026-12-25T10:00:00-05:00", "is_open": False,
                         "next_open": "2026-12-28T09:30:00-05:00",
                         "next_close": "2026-12-28T16:00:00-05:00"}
        with patch.object(backend.requests, "get", side_effect=[FakeResponse(payload=holiday_clock),
                                                                FakeResponse(payload=[])]):
            self.feed._refresh_market_clock("fake", "fake")
        self.assertEqual(self.feed.market_clock["phase"], "CLOSED")

    def test_rest_failure_preserves_existing_official_bar(self):
        original = {"time": self.base - 60, "open": 99, "high": 101,
                    "low": 98, "close": 100, "volume": 900, "origin": "cache"}
        self.feed.official[original["time"]] = original.copy()
        with patch.object(backend.requests, "get", return_value=FakeResponse(status=401, payload={})):
            self.feed.history("fake", "fake", symbol="NVDA", reconcile=True)
        self.assertEqual(self.feed.official[original["time"]], original)
        self.assertIn("HTTP 401", self.feed.history_error)

    def test_rest_reconciliation_replaces_corrected_closed_bar(self):
        self.feed.official[self.base - 60] = {"time": self.base - 60, "open": 99,
            "high": 101, "low": 98, "close": 100, "volume": 900, "origin": "websocket"}
        payload = {"bars": [{"t": stamp(self.base - 60), "o": 99, "h": 102,
                              "l": 98, "c": 101, "v": 950}], "next_page_token": None}
        with patch.object(backend.requests, "get", return_value=FakeResponse(payload=payload)):
            self.feed.history("fake", "fake", symbol="NVDA", reconcile=True)
        corrected = self.feed.official[self.base - 60]
        self.assertEqual(corrected["close"], 101)
        self.assertEqual(corrected["volume"], 950)
        self.assertEqual(corrected["origin"], "rest")


if __name__ == "__main__":
    print("Backend probado:", BACKEND)
    unittest.main(verbosity=2)
