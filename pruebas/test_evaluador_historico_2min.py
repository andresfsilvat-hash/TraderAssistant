"""Pruebas sin internet, claves ni operaciones del evaluador histórico."""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import tempfile
import unittest
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

# Ejecutable desde .\pruebas sin instalar el proyecto como paquete.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evaluador_historico_2min import (
    EC, NY, classify_move, direction_from_signals, evaluate_symbol,
    load_cache, parse_timestamp, run, summarize_events, validate_bars,
)


def regular_bars(n=80, day=(2026, 11, 17), open_price=100.0):
    dt = datetime(*day, 9, 30, tzinfo=NY)
    return [{"time": int((dt + timedelta(minutes=i)).timestamp()),
             "open": open_price, "high": open_price + 1,
             "low": open_price - 1, "close": open_price + 0.2,
             "volume": 1000} for i in range(n)]


class BacktestTests(unittest.TestCase):
    def test_timestamps_reject_naive(self):
        with self.assertRaises(ValueError):
            parse_timestamp("2026-11-17T10:00:00")
        a = parse_timestamp("2026-11-17T10:00:00-05:00")
        b = parse_timestamp("2026-11-17T15:00:00Z")
        self.assertEqual(a, b)

    def test_invalid_bars_and_duplicate_replaced(self):
        v = regular_bars(3)
        duplicates = dict(v[1], close=100.5)
        invalid = dict(v[2], high=10)
        ordered, stats = validate_bars([v[2], v[0], v[1], duplicates, invalid])
        self.assertEqual(len(ordered), 3)
        self.assertEqual(ordered[1]["close"], 100.5)
        self.assertEqual(stats["invalid"], 1)
        self.assertEqual(stats["duplicates"], 1)

    def test_excludes_provisional_and_nonminute_timestamps(self):
        b = regular_bars(2)
        bad = dict(b[0], time=b[0]["time"] + 5)
        provisional = dict(b[0], provisional=True)
        data, counts = validate_bars([*b, bad, provisional])
        self.assertEqual(len(data), 2)
        self.assertEqual(counts["unaligned"], 1)
        self.assertEqual(counts["provisional"], 1)

    def test_classification_directions(self):
        self.assertEqual(direction_from_signals(["Hammer (1m)"]), "SUBE")
        self.assertEqual(direction_from_signals(["Shooting Star (1m)"]), "BAJA")
        self.assertEqual(direction_from_signals(["Shooting Star (1m)", "Hammer (1m)"]), "CONTRADICTORIO")
        self.assertEqual(direction_from_signals([]), "SIN_SENAL")
        self.assertEqual(classify_move(10, 10), "EMPATE")

    def test_lookahead_entry_exit_at_future_opens(self):
        bars = regular_bars()
        # signal from bar 39, next-minute open bar 40, expiry 120s later bar 42
        bars[40]["open"] = 100
        bars[40]["low"] = 99
        bars[42]["open"] = 101
        bars[42]["high"] = 102
        with patch("evaluador_historico_2min.detect_patterns", return_value=["Hammer (1m)"]), \
             patch("evaluador_historico_2min.detect_indicators", return_value=[]):
            events, _, _ = evaluate_symbol("NVDA", bars)
        first = events[0]
        self.assertEqual(first["direction"], "SUBE")
        self.assertEqual(first["result"], "ACIERTO")
        self.assertEqual(first["entry_proxy_first_trade_1m"], 100)
        self.assertEqual(first["expiry_proxy_first_trade_1m"], 101)
        self.assertEqual(parse_timestamp(first["expiry_nominal_ec"]) -
                         parse_timestamp(first["entry_nominal_ec"]), 120)

    def test_no_future_peeking_signal_does_not_change(self):
        bars = regular_bars()
        def detector(df, label):
            return ["Hammer (1m)"] if float(df["Close"].iloc[-1]) >= 100.1 else ["Shooting Star (1m)"]
        with patch("evaluador_historico_2min.detect_patterns", side_effect=detector), \
             patch("evaluador_historico_2min.detect_indicators", return_value=[]):
            before, _, _ = evaluate_symbol("NVDA", bars)
            future = [dict(b) for b in bars]
            future[55]["close"] = 99.8
            future[55]["low"] = 99.0
            after, _, _ = evaluate_symbol("NVDA", future)
        self.assertEqual(before[0]["direction"], after[0]["direction"])
        self.assertEqual(before[0]["indicator_signals"], after[0]["indicator_signals"])

    def test_missing_middle_bar_discards_case(self):
        bars = regular_bars(44)
        bars = [b for j, b in enumerate(bars) if j != 41]
        with patch("evaluador_historico_2min.detect_patterns", return_value=["Hammer (1m)"]), \
             patch("evaluador_historico_2min.detect_indicators", return_value=[]):
            events, counts, _ = evaluate_symbol("NVDA", bars)
        self.assertGreaterEqual(counts["skip_missing_exit"], 1)
        self.assertEqual(len(events), 0)

    def test_never_cross_regular_session(self):
        dt = datetime(2026, 11, 17, 15, 10, tzinfo=NY)
        bars = regular_bars(70)
        bars += [{"time": int((dt + timedelta(minutes=i)).timestamp()),
                  "open": 100.0, "high": 101.0, "low": 99.0,
                  "close": 100.1, "volume": 10} for i in range(60)]
        bars, _ = validate_bars(bars)
        with patch("evaluador_historico_2min.detect_patterns", return_value=["Hammer (1m)"]), \
             patch("evaluador_historico_2min.detect_indicators", return_value=[]):
            events, stats, _ = evaluate_symbol("NVDA", bars)
        self.assertGreater(stats["skip_cross_session"], 0)
        for e in events:
            self.assertEqual(e["session_ny"], datetime.fromisoformat(e["expiry_nominal_ec"]).astimezone(NY).date().isoformat())

    def test_no_overlap_for_primary_metric(self):
        bars = regular_bars(90)
        with patch("evaluador_historico_2min.detect_patterns", return_value=["Hammer (1m)"]), \
             patch("evaluador_historico_2min.detect_indicators", return_value=[]):
            events, counts, sessions = evaluate_symbol("NVDA", bars)
        selected = [e for e in events if e["nonoverlap_selected"]]
        self.assertGreater(counts["excluded_overlap"], 0)
        for a, b in zip(selected, selected[1:]):
            self.assertGreaterEqual(parse_timestamp(b["entry_nominal_ec"]),
                                    parse_timestamp(a["expiry_nominal_ec"]))
        metrics = summarize_events(events, sessions)["metrics"]["total"]
        self.assertEqual(metrics["evaluated"], len(selected))

    def test_inadequate_session_count_always_unevaluated(self):
        bars = regular_bars(80)
        with patch("evaluador_historico_2min.detect_patterns", return_value=["Hammer (1m)"]), \
             patch("evaluador_historico_2min.detect_indicators", return_value=[]):
            events, _, sessions = evaluate_symbol("NVDA", bars)
        result = summarize_events(events, sessions)
        self.assertEqual(result["evidence_level"], "INSUFICIENTE")
        self.assertEqual(result["session_count"], 1)

    def test_hypothetical_payout_not_actual_profit(self):
        fake = [dict(nonoverlap_selected=True, direction="SUBE", result="ACIERTO",
                     baseline_result="FALLO", session_ny="2026-11-17")]
        r = summarize_events(fake, ["2026-11-17"], payout=.86)
        self.assertEqual(r["metrics"]["total"]["hypothetical_net_units"], .86)
        self.assertEqual(r["evidence_level"], "INSUFICIENTE")

    def test_cache_offline_and_report_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "cache").mkdir()
            fixture = {"symbol": "NVDA", "feed": "iex", "candles": regular_bars(80)}
            (root / "cache" / "alpaca_iex_nvda.json").write_text(json.dumps(fixture), encoding="utf-8")
            with patch("evaluador_historico_2min.detect_patterns", return_value=["Hammer (1m)"]), \
                 patch("evaluador_historico_2min.detect_indicators", return_value=[]):
                result = run(root / "cache", root / "output", ["NVDA"])
            self.assertFalse(result["real_trade_eligible"])
            self.assertTrue((root / "output" / "eventos_2min.csv").is_file())
            self.assertTrue((root / "output" / "resumen_2min.json").is_file())
            self.assertTrue((root / "output" / "informe_2min.md").is_file())
            self.assertIn("INSUFICIENTE", (root / "output" / "informe_2min.md").read_text(encoding="utf-8"))

    def test_reject_cache_feed_mismatch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "alpaca_iex_nvda.json").write_text(
                json.dumps({"symbol": "NVDA", "feed": "sip", "candles": regular_bars(5)}),
                encoding="utf-8")
            with self.assertRaises(ValueError):
                load_cache(root, "NVDA")


if __name__ == "__main__":
    unittest.main(verbosity=2)
