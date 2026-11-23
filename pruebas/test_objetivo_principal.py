from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis_live import compute_live_analysis
from decision_engine_experimental import evaluate_hypothesis
from multitimeframe_context import build_multitimeframe_context
from simulador_prospectivo_nvda_2min import ProspectiveObserver, iso


T = datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc)


def technical_analysis(candle=T - timedelta(minutes=1), *, volume=1.3, context_day="Bajista"):
    return {
        "symbol": "NVDA", "status": "ready", "stale": False,
        "last_candle_time": iso(candle), "computed_at": iso(candle + timedelta(minutes=1)),
        "bias": "Alcista", "signals": [], "patterns": [],
        "values": {"rsi_14": 52, "macd_12_26": .2, "macd_signal_9": .1,
                   "macd_histogram": .1, "macd_histogram_previous": .08,
                   "bollinger_percent_b": .6, "trend_1m": "Alcista", "volume_ratio": volume},
        "context": {"1h": {"status": "sufficient", "trend": "Alcista"},
                    "1d": {"status": "sufficient", "trend": context_day,
                           "sma50_position": "below" if context_day == "Bajista" else "above"}},
    }


class IndependentDecisionTests(unittest.TestCase):
    def test_horizons_are_directionally_independent(self):
        result = evaluate_hypothesis(technical_analysis())
        directions = {int(key): value["direccion"] for key, value in result["evaluaciones"].items()}
        self.assertEqual(directions, {60: "ESPERAR", 120: "SUBE", 300: "SUBE", 600: "ESPERAR"})
        self.assertIn("no están alineados", result["evaluaciones"]["600"]["justificacion"])

    def test_macd_fields_are_one_family_not_multiple_confirmations(self):
        result = evaluate_hypothesis(technical_analysis(volume=.8))
        self.assertEqual(result["evaluaciones"]["120"]["direccion"], "ESPERAR")
        self.assertEqual(set(result["grupos_evidencia"]).intersection({"macd", "macd_signal", "macd_histogram"}), set())
        self.assertIn("impulso_macd", result["grupos_evidencia"])

    def test_sube_baja_and_wait_are_available_for_every_horizon(self):
        bullish = technical_analysis(context_day="Alcista")
        bullish["patterns"] = bullish["signals"] = ["Hammer (1m)"]
        bearish = technical_analysis(context_day="Bajista")
        bearish["bias"] = "Bajista"
        bearish["patterns"] = bearish["signals"] = ["Shooting Star (1m)"]
        bearish["values"].update({"macd_12_26": -.2, "macd_signal_9": -.1,
                                  "macd_histogram": -.1, "macd_histogram_previous": -.08,
                                  "trend_1m": "Bajista"})
        bearish["context"]["1h"]["trend"] = "Bajista"
        waiting = {"symbol": "NVDA", "status": "insufficient", "stale": True}
        up = evaluate_hypothesis(bullish)["evaluaciones"]
        down = evaluate_hypothesis(bearish)["evaluaciones"]
        wait = evaluate_hypothesis(waiting)["evaluaciones"]
        for horizon in ("60", "120", "300", "600"):
            self.assertEqual(up[horizon]["direccion"], "SUBE", horizon)
            self.assertEqual(down[horizon]["direccion"], "BAJA", horizon)
            self.assertEqual(wait[horizon]["direccion"], "ESPERAR", horizon)


class ContextCausalityTests(unittest.TestCase):
    def test_context_excludes_future_rows(self):
        rows = []
        start = pd.Timestamp("2026-08-03 13:30:00", tz="UTC")
        days = pd.bdate_range(start=start.normalize(), periods=56, tz="UTC")
        for day_number, day in enumerate(days):
            session_start = day + timedelta(hours=13, minutes=30)
            for minute in range(60):
                timestamp = session_start + timedelta(minutes=minute)
                price = 100 + day_number * .1 + minute * .001
                rows.append((timestamp, price))
        frame = pd.DataFrame({"Open": [p for _, p in rows], "High": [p + .02 for _, p in rows],
                              "Low": [p - .02 for _, p in rows], "Close": [p for _, p in rows],
                              "Volume": [1000 for _ in rows]}, index=[t for t, _ in rows])
        cutoff = rows[-61][0]
        future = frame.index > cutoff
        frame.loc[future, ["Open", "High", "Low", "Close"]] = 9999
        with tempfile.TemporaryDirectory() as folder:
            context = build_multitimeframe_context(frame, as_of=cutoff, project_root=folder)
        self.assertEqual(context["future_rows_used"], 0)
        self.assertLess(context["1h"].get("close", 0), 9999)
        self.assertEqual(context["1d"]["status"], "sufficient")


class FullFlowTests(unittest.TestCase):
    def test_closed_candle_reaches_experimental_evaluation(self):
        candles = []
        for index in range(80):
            price = 100 + index * .05
            candles.append({"time": int(T.timestamp()) - (80 - index) * 60,
                            "open": price, "high": price + .1, "low": price - .1,
                            "close": price + .04, "volume": 1000 + index, "provisional": False})
        context = {"status": "sufficient", "future_rows_used": 0,
                   "1h": {"status": "sufficient", "trend": "Alcista"},
                   "1d": {"status": "sufficient", "trend": "Alcista", "sma50_position": "above"}}
        with patch("analysis_live.build_multitimeframe_context", return_value=context):
            result = compute_live_analysis({"symbol": "NVDA", "source": "test", "feed_revision": 7,
                                            "candles": candles})
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["context"]["future_rows_used"], 0)
        self.assertEqual(set(result["experimental_decision"]["evaluaciones"]), {"60", "120", "300", "600"})

    def test_trade_derived_5s_proxy_records_source_and_timing(self):
        with tempfile.TemporaryDirectory() as folder:
            observer = ProspectiveObserver(Path(folder), started=T, horizons=(120,))
            first = technical_analysis(T - timedelta(minutes=2), context_day="Alcista")
            second = technical_analysis(T - timedelta(minutes=1), context_day="Alcista")
            second["computed_at"] = iso(T + timedelta(seconds=1))
            observer.process(first, {"symbol": "NVDA"}, T)
            observer.process(second, {"symbol": "NVDA"}, T + timedelta(seconds=1))
            market = {"symbol": "NVDA", "short_candles": [{"time": int((T + timedelta(seconds=5)).timestamp()),
                                                               "close": 100, "open": 100, "high": 100,
                                                               "low": 100, "volume": 10}]}
            observer.process(second, market, T + timedelta(seconds=7))
            self.assertEqual(observer.pending[0]["fuente_entrada"], "IEX_VELA_5S_TRADE_CLOSE_PROXY")
            self.assertGreater(datetime.fromisoformat(observer.pending[0]["entrada_utc"]),
                               datetime.fromisoformat(observer.pending[0]["senal_detectada_utc"]))
            self.assertTrue(observer.pending[0]["aviso_pantalla_utc"])
            self.assertTrue(observer.pending[0]["analisis_disponible_utc"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
