"""Pruebas sin red de Alpaca Cripto 24/7, aislado del motor NVDA."""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
import json
import unittest

from flask import Flask
import crypto_live
from crypto_live import CryptoFeed, _parse_bar, register_crypto_live


STAMP = "2026-11-23T21:00:00Z"


class MockWebSocket:
    def __init__(self):
        self.sent = []

    def send(self, raw):
        self.sent.append(json.loads(raw))


class CryptoV5Tests(unittest.TestCase):
    def test_catalogo_24_7_y_prohibicion_de_ordenes(self):
        f = CryptoFeed()
        x = f.snapshot()
        self.assertEqual(x["symbol"], "BTC/USD")
        self.assertEqual(x["market_hours"], "24/7")
        self.assertEqual(set(x["available_symbols"]), {"BTC/USD", "ETH/USD", "SOL/USD"})
        self.assertFalse(x["operativa_autorizada"])
        self.assertNotIn("orden", x)
        self.assertNotIn("secret", json.dumps(x))

    def test_barras_oficiales_y_correcciones(self):
        feed = CryptoFeed()
        ws = MockWebSocket()
        bar = {"T": "b", "S": "BTC/USD", "t": STAMP,
               "o": 95000, "h": 95100, "l": 94900, "c": 95050, "v": 4.5}
        feed._handle(bar, ws, True)
        initial = feed.snapshot()["candles"]
        self.assertEqual(len(initial), 1)
        self.assertFalse(initial[0]["provisional"])
        correction = dict(bar, T="u", c=94980)
        feed._handle(correction, ws, True)
        self.assertEqual(len(feed.snapshot()["candles"]), 1)
        self.assertEqual(feed.snapshot()["candles"][0]["close"], 94980)
        self.assertEqual(ws.sent, [])

    def test_rechaza_prever_barra_con_datos_corruptos(self):
        with self.assertRaises(ValueError):
            _parse_bar({"t": STAMP, "o": 100, "h": 95,
                        "l": 90, "c": 99, "v": 10})
        f = CryptoFeed()
        f._handle({"T": "b", "S": "BTC/USD", "t": STAMP,
                   "o": 100, "h": 95, "l": 90, "c": 99, "v": 10}, MockWebSocket(), True)
        self.assertEqual(f.snapshot()["candles"], [])

    def test_trades_cotizaciones_y_simbolo_ajeno_ignorados(self):
        f = CryptoFeed()
        f._handle({"T": "t", "S": "ETH/USD", "t": STAMP, "p": 500, "s": 1}, MockWebSocket(), True)
        self.assertIsNone(f.snapshot()["last_trade"])
        f._handle({"T": "t", "S": "BTC/USD", "t": STAMP, "p": 90000, "s": 1.4}, MockWebSocket(), True)
        f._handle({"T": "q", "S": "BTC/USD", "t": STAMP, "bp": 89999,
                   "ap": 90001}, MockWebSocket(), True)
        x = f.snapshot()
        self.assertEqual(x["last_trade"]["price"], 90000)
        self.assertEqual(x["last_quote"]["mid"], 90000)
        self.assertEqual(x["trade_count"], 1)
        self.assertEqual(x["quote_count"], 1)

    def test_cambio_simbolo_aisla_datos(self):
        f = CryptoFeed()
        f._handle({"T": "t", "S": "BTC/USD", "t": STAMP, "p": 90000, "s": 1}, MockWebSocket(), True)
        f.select_symbol("ETH/USD")
        x = f.snapshot()
        self.assertEqual(x["symbol"], "ETH/USD")
        self.assertEqual(x["candles"], [])
        self.assertIsNone(x["last_trade"])
        self.assertEqual(x["trade_count"], 0)
        with self.assertRaises(ValueError):
            f.select_symbol(["BTC/USD"])
        with self.assertRaises(ValueError):
            f.select_symbol("NVDA")

    def test_acepta_confirmacion_de_suscripcion_solo_par_vigente(self):
        f = CryptoFeed()
        ws = MockWebSocket()
        auth, fatal = f._handle({"T": "success", "msg": "authenticated"}, ws, False)
        self.assertTrue(auth)
        self.assertFalse(fatal)
        self.assertEqual(ws.sent, [])  # evitar dos suscripciones tras autenticar
        f._handle({"T": "subscription", "trades": ["BTC/USD"],
                   "bars": ["BTC/USD"]}, ws, True)
        self.assertEqual(f.snapshot()["status"], "conectado")
        f.select_symbol("SOL/USD")
        f._handle({"T": "subscription", "bars": ["BTC/USD"]}, ws, True)
        self.assertNotEqual(f.snapshot()["status"], "conectado")

    def test_error_autenticacion_bloquea_conexion(self):
        f = CryptoFeed()
        authorized, fatal = f._handle({"T": "error", "code": 401}, MockWebSocket(), False)
        self.assertFalse(authorized)
        self.assertTrue(fatal)
        self.assertEqual(f.snapshot()["status"], "error")

    def test_endpoints_aislados_y_metodos(self):
        app = Flask(__name__, static_folder=str(Path(__file__).resolve().parents[1] / "ui"))
        app.testing = True
        register_crypto_live(app)
        with patch.object(crypto_live._feed, "start"):
            r = app.test_client().get("/api/crypto/live")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json["market_hours"], "24/7")
        self.assertFalse(r.json["operativa_autorizada"])
        self.assertEqual(r.headers["Cache-Control"], "no-store")
        self.assertEqual(app.test_client().post("/api/crypto/live").status_code, 405)
        self.assertEqual(app.test_client().get("/crypto").status_code, 200)
        self.assertEqual(app.test_client().post("/api/crypto/symbol", json={"symbol": ["BTC/USD"]}).status_code, 400)
        self.assertEqual(app.test_client().post("/api/crypto/symbol", json={"symbol": "NVDA"}).status_code, 400)

    def test_interfaz_tiene_enlace_a_mercado_crito(self):
        ui = Path(__file__).resolve().parents[1] / "ui"
        self.assertIn('href="/crypto"', (ui / "live.html").read_text(encoding="utf-8"))
        crypto = (ui / "crypto.html").read_text(encoding="utf-8")
        self.assertIn("/api/crypto/live", crypto)
        self.assertIn("NO genera señales", crypto)


if __name__ == "__main__":
    unittest.main()
