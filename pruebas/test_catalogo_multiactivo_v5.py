"""Pruebas del catálogo ampliado REALTIME, sin conexión externa ni órdenes."""
from datetime import datetime, timezone
from pathlib import Path
import unittest
from unittest.mock import patch

from alpaca_live import LiveFeed, SYMBOLS
from decision_engine_experimental import evaluate_hypothesis


class CatalogoRealtimeV5Tests(unittest.TestCase):
    def test_24_activos_mismo_horario_y_anteriores_conservados(self):
        self.assertEqual(len(SYMBOLS), 24)
        self.assertTrue({"NVDA", "SPY", "QQQ", "MSFT", "AAPL", "AMD"}.issubset(SYMBOLS))
        self.assertTrue({"AMZN", "META", "TSLA", "JPM", "GLD", "IWM", "TLT"}.issubset(SYMBOLS))
        self.assertTrue(all(symbol.isalpha() and symbol.isupper() for symbol in SYMBOLS))

    def test_cambio_de_activo_no_abre_conexiones_adicionales(self):
        feed = LiveFeed()
        with patch.object(feed, "_save_cache"), patch.object(feed, "_restore_cache"), \
             patch.object(feed, "start", side_effect=AssertionError("No se debe iniciar WS")):
            feed.select_symbol("PLTR")
        self.assertEqual(feed.snapshot()["symbol"], "PLTR")
        self.assertEqual(feed.snapshot()["available_symbols"], SYMBOLS)
        self.assertEqual(feed.short_bars, [])
        self.assertIsNone(feed.last_trade)
        self.assertIsNone(feed.last_received_at)

    def test_activo_desconocido_se_rechaza(self):
        feed = LiveFeed()
        with self.assertRaises(ValueError):
            feed.select_symbol("BTC/USD")
        self.assertEqual(feed.snapshot()["symbol"], "NVDA")

    def test_interfaz_carga_catalogo_desde_servidor(self):
        html = (Path(__file__).resolve().parents[1] / "ui" / "live.html").read_text(encoding="utf-8")
        self.assertIn("renderSymbolCatalog(data.available_symbols)", html)
        self.assertIn("select.replaceChildren(group)", html)
        self.assertIn("Acciones y ETF EE. UU.", html)

    def test_no_habilita_predicciones_no_validadas_para_otro_activo(self):
        a = {"symbol": "META", "status": "ready", "stale": False,
             "last_candle_time": "2026-11-23T15:00:00+00:00",
             "computed_at": datetime(2026, 11, 23, 15, 1, tzinfo=timezone.utc).isoformat(),
             "values": {"trend_1m": "Alcista", "macd_12_26": 2,
                        "macd_signal_9": 1, "macd_histogram": 1, "volume_ratio": 3},
             "context": {"1h": {"status": "sufficient", "trend": "Alcista"}}}
        out = evaluate_hypothesis(a)
        self.assertTrue(all(x["direccion"] == "ESPERAR" for x in out["evaluaciones"].values()))
        self.assertEqual(out["decision_operativa_validada"], "ESPERAR")


if __name__ == "__main__":
    unittest.main()
